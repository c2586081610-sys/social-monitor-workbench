"""health 业务：凭据健康度 + 系统健康 + 监控层在线探测。"""
from __future__ import annotations

import json
import time

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories import health_repo
from app.schemas.health import CookieHealth, SystemHealth

_COOKIE_PLATFORMS = ["douyin", "bilibili", "xhs", "twitter"]


def _heartbeat_age() -> float | None:
    path = settings.monitor_heartbeat_file
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return time.time() - float(payload.get("ts", 0))
    except (OSError, ValueError, TypeError):
        return None


def is_monitor_online() -> bool:
    age = _heartbeat_age()
    if age is None:
        return False
    return age <= settings.monitor_heartbeat_timeout


def _http_status(url: str) -> str:
    if not url:
        return "unknown"
    try:
        resp = httpx.get(url, timeout=3, follow_redirects=True)
        return "online" if resp.status_code < 500 else "degraded"
    except (httpx.HTTPError, OSError):
        return "offline"


class HealthService:
    def cookie_health(self, db: Session) -> list[CookieHealth]:
        rows = health_repo.list_cookies(db)
        by_platform = {row.platform: row for row in rows}
        items = []
        for platform in _COOKIE_PLATFORMS:
            row = by_platform.get(platform)
            if row is None:
                items.append(
                    CookieHealth(platform=platform, status="UNKNOWN", last_checked_at=None, expires_at=None, note=None)
                )
            else:
                items.append(
                    CookieHealth(
                        platform=row.platform,
                        status=row.status,
                        last_checked_at=row.last_checked_at,
                        expires_at=row.expires_at,
                        note=row.note,
                    )
                )
        return items

    def system_health(self) -> list[SystemHealth]:
        items = [
            SystemHealth(component="aggregator", status="online", detail="聚合 API 运行中"),
            SystemHealth(
                component="monitor",
                status="online" if is_monitor_online() else "offline",
                detail=None if is_monitor_online() else "监控层心跳超时",
            ),
            SystemHealth(
                component="rsshub",
                status=_http_status(f"{settings.rsshub_base_url}/health") if settings.rsshub_base_url else "unknown",
                detail=None if settings.rsshub_base_url else "未配置 RSSHUB_BASE_URL",
            ),
            SystemHealth(
                component="changedetection",
                status=_http_status(settings.changedetection_url) if settings.changedetection_url else "unknown",
                detail=None if settings.changedetection_url else "未配置 CHANGEDETECTION_URL",
            ),
            SystemHealth(
                component="downloader",
                status=self._downloader_status(),
                detail=self._downloader_detail(),
            ),
            SystemHealth(
                component="transcriber",
                status=self._transcriber_status(),
                detail=self._transcriber_detail(),
            ),
            SystemHealth(
                component="workbuddy_pending",
                status=self._pending_status(),
                detail="素材就绪清单目录可写" if settings.pending_dir.exists() else "待创建",
            ),
        ]
        return items

    @staticmethod
    def _downloader_paths() -> list[tuple[str, str]]:
        """已配置的下载器路径 [(env_name, path)]：DOWNLOADER_BIN 与 DOUYIN_DOWNLOADER_DIR 任一即可。"""
        paths: list[tuple[str, str]] = []
        if settings.downloader_bin:
            paths.append(("DOWNLOADER_BIN", settings.downloader_bin))
        if settings.douyin_downloader_dir:
            paths.append(("DOUYIN_DOWNLOADER_DIR", settings.douyin_downloader_dir))
        return paths

    @classmethod
    def _downloader_status(cls) -> str:
        from pathlib import Path

        paths = cls._downloader_paths()
        if not paths:
            return "unknown"
        return "online" if any(Path(path).exists() for _, path in paths) else "offline"

    @classmethod
    def _downloader_detail(cls) -> str | None:
        from pathlib import Path

        paths = cls._downloader_paths()
        if not paths:
            return "未配置下载器"
        missing = [name for name, path in paths if not Path(path).exists()]
        return f"配置的下载器路径不存在: {', '.join(missing)}" if missing else None

    @staticmethod
    def _transcriber_status() -> str:
        if not settings.transcriber_engine:
            return "unknown"
        try:
            __import__("funasr")
            return "online"
        except ImportError:
            return "offline"

    @staticmethod
    def _transcriber_detail() -> str | None:
        if not settings.transcriber_engine:
            return "未配置 TRANSCRIBER_ENGINE"
        try:
            __import__("funasr")
            return None
        except ImportError:
            return "funasr 未安装"

    @staticmethod
    def _pending_status() -> str:
        try:
            settings.pending_dir.mkdir(parents=True, exist_ok=True)
            return "online"
        except OSError:
            return "offline"


health_service = HealthService()
