"""小红书监测适配器：复用 tools/xhs_fetch_notes.py（Playwright 拦截 user_posted API）。

- 打开博主主页 URL → 拦截 user_posted API 响应 → 拿 note_id + xsec_token（无需 URL 带 token）
- cookie：优先 config/platform_cookies.json 的 xhs.cookie（Edge 提取），fallback xhs_profile
- 子进程隔离：subprocess 调 managed python 执行 xhs_fetch_notes.py（该脚本用 playwright，非 MediaCrawler）
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("monitor.xhs_mediacrawler")

_ROOT = Path(__file__).resolve().parents[2]
_FETCH_SCRIPT = _ROOT / "tools" / "xhs_fetch_notes.py"
_PYTHON = sys.executable


class XhsMediacrawlerAdapter:
    """小红书博主最新笔记抓取（Playwright 拦截 user_posted API）。"""

    def __init__(self, timeout: int = 180) -> None:
        self.timeout = timeout

    def available(self) -> bool:
        return _FETCH_SCRIPT.exists()

    def poll_creator(self, creator_url: str) -> list[dict]:
        """抓取博主最新笔记列表。creator_url = 博主主页 URL（无需带 xsec_token）。

        返回：[{platform, external_id, title, url, published_at, content_type}]
        """
        if not creator_url:
            return []
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            out_path = tmp.name
        try:
            proc = subprocess.run(
                [_PYTHON, str(_FETCH_SCRIPT), creator_url, out_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            logger.warning("xhs 抓取超时（>%ss）", self.timeout)
            return []
        if proc.returncode != 0:
            logger.warning("xhs 抓取失败 rc=%s err=%s", proc.returncode, (proc.stderr or "")[-300:])
            return []
        try:
            notes = json.loads(Path(out_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass
        items = []
        for n in notes:
            nid = n.get("note_id") or ""
            if not nid:
                continue
            xsec = n.get("xsec_token") or ""
            url = f"https://www.xiaohongshu.com/explore/{nid}"
            if xsec:
                url += f"?xsec_token={xsec}&xsec_source=pc_feed"
            # time 字段：小红书 API 返回毫秒时间戳
            ts = n.get("time") or 0
            published_at = None
            try:
                t = int(ts)
                if t > 10**12:
                    t //= 1000
                if t > 0:
                    from datetime import datetime, timezone

                    published_at = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError, OSError):
                pass
            items.append(
                {
                    "platform": "xhs",
                    "external_id": nid,
                    "title": n.get("title") or "",
                    "url": url,
                    "published_at": published_at,
                    "content_type": "image" if not n.get("has_video") else "video",
                }
            )
        return items
