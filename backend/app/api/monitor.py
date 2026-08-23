"""monitor 路由：/api/v1/monitor/poll。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_admin
from app.core.errors import ok
from app.schemas.common import Platform
from app.services.monitor_service import monitor_service


class PollRequest(BaseModel):
    platform: Platform | None = None


router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"], dependencies=[Depends(require_admin)])


@router.post("/poll", status_code=200)
def trigger_poll(payload: PollRequest | None = None):
    platform = payload.platform if payload else None
    return ok(monitor_service.trigger_poll(platform))
