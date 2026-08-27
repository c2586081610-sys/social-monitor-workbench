"""monitor 路由：/api/v1/monitor/poll、poll-now、poll-status。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.schemas.common import Platform
from app.services.monitor_service import monitor_service


class PollRequest(BaseModel):
    platform: Platform | None = None


class PollNowRequest(BaseModel):
    platform: Platform | None = None
    creator_id: int | None = Field(default=None, ge=1)


router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"], dependencies=[Depends(require_admin)])


@router.post("/poll", status_code=200)
def trigger_poll(payload: PollRequest | None = None):
    platform = payload.platform if payload else None
    return ok(monitor_service.trigger_poll(platform))


@router.post("/poll-now", status_code=200)
def trigger_poll_now(payload: PollNowRequest | None = None):
    """立即爬取：不依赖监控层常驻，拉起一次性爬取子进程后立即返回。"""
    platform = payload.platform if payload else None
    creator_id = payload.creator_id if payload else None
    return ok(monitor_service.trigger_onetime_poll(platform, creator_id))


@router.get("/poll-status", status_code=200)
def get_poll_status(db: Session = Depends(get_db)):
    """各平台最近爬取时间（读 poll_logs）。"""
    return ok(monitor_service.poll_status(db))
