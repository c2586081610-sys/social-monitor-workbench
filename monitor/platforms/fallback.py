"""changedetection.io 兜底对接占位（K4/K5：仅兜底非主路径，需正确 selector 防误报）。"""
from __future__ import annotations

import httpx


class ChangedetectionAdapter:
    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url.rstrip("/")

    def health(self) -> dict:
        if not self.base_url:
            return {"status": "unknown", "note": "未配置 CHANGEDETECTION_URL"}
        try:
            resp = httpx.get(self.base_url, timeout=3, follow_redirects=True)
            status = "online" if resp.status_code < 500 else "degraded"
            return {"status": status, "note": None}
        except httpx.HTTPError:
            return {"status": "offline", "note": "连接失败"}

    def poll_watches(self, watch_urls: list[str]) -> list[dict]:
        """P1 占位：真实检测由 changedetection 自身调度，本类仅登记接入契约。"""
        return []
