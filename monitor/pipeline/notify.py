"""流水线·通知：写「素材就绪清单」供 WorkBuddy AI 层消费（SPEC §10），并登记 note 任务。"""
from __future__ import annotations

import logging

from app.repositories import task_repo
from app.services.note_service import write_pending_manifest

logger = logging.getLogger("monitor.pipeline.notify")


def notify_ready(db, work) -> str:
    """下载+转写+抽帧完成后调用：生成 workbuddy/pending/*.json，返回相对路径。"""
    pending = write_pending_manifest(work)
    task_repo.upsert(db, work.id, "note", "pending", error=None, attempts=0)
    logger.info("素材就绪清单已生成: %s", pending)
    return pending
