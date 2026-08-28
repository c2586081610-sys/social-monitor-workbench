"""RSSHub 路由接入适配器（B站/小红书/推特）：feedparser 解析，路由可配置。

K4：自建 RSSHub 实例；路由失效 → 分类写入 poll_logs，由 changedetection 兜底。
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

import feedparser
import httpx

logger = logging.getLogger("monitor.rsshub")

# 路由模板：{external_id} = uid / user_id / handle
# v0.4：twitter user 路由开启 includeReplies=1&includeRts=1（监测 原创+转推+回复）；twitter_likes 监测点赞
ROUTES = {
    "bilibili": "bilibili/user/video/{external_id}",
    "xhs": "xiaohongshu/user/{external_id}",
    "twitter": "twitter/user/{external_id}?includeReplies=1&includeRts=1",
    "twitter_likes": "twitter/likes/{external_id}",
}


class RSSHubError(Exception):
    """轮询失败，携带分类：cookie / network / route / rate_limit / unknown（K3）。"""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        self.message = message
        super().__init__(message)


def _clean_title(raw: str) -> str:
    return " ".join(raw.replace("\n", " ").split())[:200]


def _iso_from_feed(entry) -> str | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


class RSSHubRouterAdapter:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def fetch_entries(self, platform: str, external_id: str, route: str | None = None) -> list[dict]:
        """拉取 RSSHub 条目。

        Args:
            platform: 平台标识（写库用，twitter_likes 的条目仍标 platform='twitter'）
            external_id: 博主外部 ID（handle / uid）
            route: 路由键（默认等于 platform；twitter_likes 场景传 'twitter_likes'）
        """
        route_key = route or platform
        route_tpl = ROUTES.get(route_key)
        if route_tpl is None:
            raise RSSHubError("route", f"平台 {platform} 无 RSSHub 路由")
        url = f"{self.base_url}/{route_tpl.format(external_id=external_id)}"
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise RSSHubError("network", f"请求失败: {exc}") from exc
        if resp.status_code == 403:
            raise RSSHubError("cookie", "HTTP 403 疑似 cookie 失效")
        if resp.status_code == 429:
            raise RSSHubError("rate_limit", "HTTP 429 触发限流")
        if resp.status_code >= 400:
            raise RSSHubError("route", f"路由失效 HTTP {resp.status_code}")
        feed = feedparser.parse(resp.text)
        entries = []
        for entry in feed.entries:
            item = self._to_work(platform, entry)
            if item:
                entries.append(item)
        return entries

    @staticmethod
    def _to_work(platform: str, entry) -> dict | None:
        external_id = RSSHubRouterAdapter._extract_id(platform, entry)
        if not external_id:
            return None
        item = {
            "platform": platform,
            "external_id": external_id,
            "title": _clean_title(entry.get("title", "")),
            "url": entry.get("link", ""),
            "published_at": _iso_from_feed(entry),
        }
        # v0.4：解析推文正文媒体，供图文/视频分流（twitter 特有；其他平台保持原样）
        if platform == "twitter":
            content_type, image_urls = RSSHubRouterAdapter._parse_twitter_media(entry)
            item["content_type"] = content_type
            item["media_urls"] = image_urls
            item["cover_url"] = image_urls[0] if image_urls else None
        else:
            # 其他平台（bilibili 等）：RSS 条目 image 字段作封面
            item["cover_url"] = entry.get("image") or None
            item["content_type"] = "video"
        return item

    @staticmethod
    def _parse_twitter_media(entry) -> tuple[str, list[str]]:
        """从 RSSHub twitter 条目描述解析媒体：content_type(video/image) + 图片直链(twimg orig)。

        判定规则（RSSHub 升级容错）：
        - 描述含 <video 或视频扩展名 → video
        - 否则含 twimg/pbs.twimg.com 图片链接 → image（尽量替换为 ?name=orig 原图）
        - 兜底：一律按图文处理（最坏丢视频不丢文）
        """
        summary = entry.get("summary", "") or entry.get("description", "") or ""
        # RSSHub 描述是 XML 转义的（&lt;img&gt; &quot; &amp;），先还原再解析
        summary = html.unescape(summary)
        image_urls: list[str] = []
        if "<video" in summary.lower() or re.search(r"\.(mp4|m3u8|mov)(\?|&|\")", summary, re.I):
            return "video", image_urls
        for src in re.findall(r'<img[^>]+src="([^"]+)"', summary):
            src = src.replace("&amp;", "&")
            if "twimg.com" in src or "pbs.twimg.com" in src:
                src = re.sub(r"\?name=[^&]*", "?name=orig", src)
                if src not in image_urls:
                    image_urls.append(src)
        return ("image" if image_urls else "text"), image_urls

    @staticmethod
    def _extract_id(platform: str, entry) -> str | None:
        guid = entry.get("id") or entry.get("guid") or ""
        link = entry.get("link") or ""
        if platform == "bilibili":
            for prefix in ("bilibili://video/", "https://www.bilibili.com/video/"):
                if guid.startswith(prefix):
                    return guid[len(prefix):].split("?")[0]
                if link.startswith(prefix):
                    return link[len(prefix):].split("?")[0]
            if "av" in guid or "BV" in guid:
                return guid.split("/")[-1]
        if platform == "xhs":
            for prefix in ("https://www.xiaohongshu.com/explore/", "https://www.xiaohongshu.com/discovery/item/"):
                if link.startswith(prefix):
                    return link[len(prefix):].split("?")[0]
        if platform == "twitter":
            if "/status/" in link:
                return link.rsplit("/status/", 1)[1].split("?")[0]
        return guid.split("/")[-1] or None
