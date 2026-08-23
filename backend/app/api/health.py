"""health 路由：/api/v1/health/*。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.services.health_service import health_service

router = APIRouter(prefix="/api/v1/health", tags=["health"], dependencies=[Depends(require_admin)])


@router.get("/cookie", status_code=200)
def get_cookie_health(db: Session = Depends(get_db)):
    return ok({"items": [c.model_dump() for c in health_service.cookie_health(db)]})


@router.get("/system", status_code=200)
def get_system_health():
    return ok({"items": [c.model_dump() for c in health_service.system_health()]})
