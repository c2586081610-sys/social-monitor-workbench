"""monitor 业务：手动触发轮询（trigger 文件）+ 立即爬取（一次性子进程）+ 轮询状态。"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import monitor_offline, validation
from app.repositories import health_repo
from app.services.health_service import is_monitor_online
from app.utils.timeutil import now_iso

# 一次性爬取支持的平台（与 monitor/jobs.RSSHUB_PLATFORMS + douyin 对齐）
_ONETIME_PLATFORMS = ("bilibili", "xhs", "twitter", "douyin")
_PLATFORM_ORDER = ("douyin", "bilibili", "xhs", "twitter")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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

    def trigger_onetime_poll(self, platform: str | None, creator_id: int | None) -> dict:
        """立即爬取：不依赖监控层常驻，拉起一次性爬取子进程后立即返回。

        Args:
            platform: 平台（bilibili/xhs/twitter/douyin），与 creator_id 二选一
            creator_id: 博主 ID，与 platform 二选一
        Returns:
            {"triggered": True, "pid": <子进程 pid>}
        """
        if platform and creator_id is not None:
            raise validation("platform 与 creator_id 只能二选一")
        if platform and platform not in _ONETIME_PLATFORMS:
            raise validation(f"platform 仅支持 {'/'.join(_ONETIME_PLATFORMS)}")
        if creator_id is not None and creator_id < 1:
            raise validation("creator_id 必须为正整数")
        script = settings.workspace_root / "monitor" / "onetime_poll.py"
        if not script.exists():
            raise validation(f"一次性爬取脚本缺失: {script}")
        cmd = [sys.executable, str(script)]
        if platform:
            cmd += ["--platform", platform]
        if creator_id is not None:
            cmd += ["--creator", str(creator_id)]
        settings.workbuddy_dir.mkdir(parents=True, exist_ok=True)
        log_path = settings.workbuddy_dir / "onetime_poll.log"
        with open(log_path, "ab") as log_fh:
            proc = subprocess.Popen(
                cmd,
                cwd=str(settings.workspace_root),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=_CREATE_NO_WINDOW,
            )
        return {"triggered": True, "pid": proc.pid}

    def poll_status(self, db: Session) -> dict:
        """各平台最近一次爬取时间（读 poll_logs，按平台取最新 finished_at）。"""
        latest = health_repo.latest_poll_logs(db)
        items = []
        for platform in _PLATFORM_ORDER:
            log = latest.get(platform)
            if log is None:
                items.append({"platform": platform, "last_poll_at": None, "status": "never"})
            else:
                items.append(
                    {"platform": platform, "last_poll_at": log.finished_at, "status": log.status}
                )
        return {"items": items}


monitor_service = MonitorService()
