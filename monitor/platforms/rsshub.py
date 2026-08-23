"""RSSHub 路由接入适配器（B站/小红书/推特）：feedparser 解析，路由可配置。

K4：自建 RSSHub 实例；路由失效 → 分类写入 poll_logs，由 changedetection 兜底。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import httpx

logger = logging.getLogger("monitor.rsshub")

# 路由模板：{external_id} = uid / user_id / handle
ROUTES = {
    "bilibili": "bilibili/user/video/{external_id}",
    "xhs": "xiaohongshu/user/{external_id}",
    "twitter": "twitter/user/{external_id}",
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

    def fetch_entries(self, platform: str, external_id: str) -> list[dict]:
        route = ROUTES.get(platform)
        if route is None:
            raise RSSHubError("route", f"平台 {platform} 无 RSSHub 路由")
        url = f"{self.base_url}/{route.format(external_id=external_id)}"
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
        return {
            "platform": platform,
            "external_id": external_id,
            "title": _clean_title(entry.get("title", "")),
            "url": entry.get("link", ""),
            "published_at": _iso_from_feed(entry),
        }

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
