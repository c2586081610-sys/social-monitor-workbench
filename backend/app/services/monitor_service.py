"""monitor 业务：手动触发轮询（通过 trigger 文件与监控层解耦通信）。"""
from __future__ import annotations

import json
import uuid

from app.core.config import settings
from app.core.errors import monitor_offline
from app.services.health_service import is_monitor_online
from app.utils.timeutil import now_iso


class MonitorService:
    def trigger_poll(self, platform: str | None) -> dict:
        if not is_monitor_online():
            raise monitor_offline()
        settings.trigger_dir.mkdir(parents=True, exist_ok=True)
        filename = f"poll-{platform or 'all'}-{now_iso().replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}.json"
        payload = {
            "platform": platform,
            "created_at": now_iso(),
            "status": "pending",
        }
        path = settings.trigger_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {"triggered": True}


monitor_service = MonitorService()
