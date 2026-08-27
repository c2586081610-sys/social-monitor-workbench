"""推特图文下载：curl_cffi（impersonate='chrome120'）+ 代理下载 twimg 原图，写 manifest。

v0.4 新增。背景（实测 2026-08-24）：
- x.com 对普通 curl/requests 做 TLS 指纹拦截，必须 curl_cffi impersonate='chrome120'
- 国内访问 x.com / twimg 需代理（本机 127.0.0.1:7892），twimg 走代理直连亦可
- 推文图片 URL 带 ?name=orig 参数时为原图；RSSHub 描述里已是 orig

manifest 复用 frames.write_manifest 格式：{work_id, semantic_aligned, fallback, frames:[{file, source_url}]}
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests as cffi_requests

logger = logging.getLogger("monitor.pipeline.twitter_image")

# 默认走本机代理；TWITTER_PROXY 环境变量可覆盖
DEFAULT_PROXY = os.getenv("TWITTER_PROXY", "http://127.0.0.1:7892")


class TwitterImageError(Exception):
    """图文下载失败。"""


def _session() -> cffi_requests.Session:
    s = cffi_requests.Session(impersonate="chrome120")
    s.proxies = {"http": DEFAULT_PROXY, "https": DEFAULT_PROXY}
    return s


def download_image(session, url: str, out_dir: Path, index: int) -> dict | None:
    """下载单张图片，返回 {file, source_url}；失败返回 None（不阻断整篇）。"""
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("图片下载失败 index=%s url=%s err=%s", index, url[:80], exc)
        return None
    if not resp.content:
        return None
    # 文件名：index-<host尾段>.<ext>，防重名与非法字符
    suffix = Path(urlparse(url).path).suffix or ".jpg"
    if suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        suffix = ".jpg"
    fname = f"{index:03d}{suffix}"
    path = out_dir / fname
    retry_write_text(path, resp.content, binary=True)
    return {"file": fname, "source_url": url}


def download_images(work, images_dir: Path) -> Path:
    """按 work.media_urls 下载全部图片，写 frame_manifest.json，返回 manifest 路径。

    media_urls 为 JSON 数组（monitor.platforms.rsshub 解析推文描述得到）；
    缺失或全部失败时写空 manifest（downstream 按无图处理，不抛错）。
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    urls: list[str] = []
    if work.media_urls:
        try:
            urls = json.loads(work.media_urls)
        except (TypeError, json.JSONDecodeError):
            urls = []
    if not isinstance(urls, list):
        urls = []
    frames: list[dict] = []
    if urls:
        session = _session()
        for i, url in enumerate(urls, start=1):
            item = download_image(session, url, images_dir, i)
            if item:
                frames.append(item)
    manifest = {
        "work_id": work.id,
        "semantic_aligned": False,
        "fallback": not urls,
        "frames": frames,
        "media_type": "image",
    }
    path = images_dir / "frame_manifest.json"
    retry_write_text(path, json.dumps(manifest, ensure_ascii=False, indent=2))
    logger.info("twitter 图文 work=%s 图片 %d/%d 下载完成 -> %s", work.id, len(frames), len(urls), path)
    return path


def retry_write_text(path: Path, content, binary: bool = False) -> None:
    """写文件，失败删后重建（WorkBuddy 沙盒覆盖写兼容，见项目记忆）。"""
    try:
        if binary:
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    except OSError:
        path.unlink(missing_ok=True)
        if binary:
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
