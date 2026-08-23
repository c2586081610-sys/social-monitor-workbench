"""抖音 CDP 持活会话占位（P1 可配置开关；P2 由 Patchright 完整实现）。

K1/K2：不用静态 cookie 做监控主路径；CDP 持活会话可续 cookie，轮询间隔默认 ≥10min。
P1 行为：未启用 → 不轮询；启用但 profile 缺失 → NEEDS_RELOGIN；就绪 → 占位返回空。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("monitor.douyin_cdp")


class DouyinCDPSession:
    def __init__(self, enabled: bool = False, profile_dir: str | None = None) -> None:
        self.enabled = enabled
        self.profile_dir = profile_dir

    def check(self) -> dict:
        """返回 {status: UNKNOWN/OK/NEEDS_RELOGIN, note}。"""
        if not self.enabled:
            return {"status": "UNKNOWN", "note": "未启用 CDP 会话（ENABLE_DOUYIN_CDP=false）"}
        if not self.profile_dir or not Path(self.profile_dir).exists():
            return {"status": "NEEDS_RELOGIN", "note": "抖音登录态缺失，需重新登录（扫码）"}
        return {"status": "OK", "note": "CDP 会话占位就绪"}

    def poll_creator(self, creator) -> list[dict]:
        """返回该博主新作品列表；P1 占位恒空。P2 走 aweme 分页 + browser_fallback。"""
        if not self.enabled:
            return []
        if self.check()["status"] != "OK":
            return []
        logger.info("douyin cdp poll placeholder for creator=%s", creator.external_id)
        return []
