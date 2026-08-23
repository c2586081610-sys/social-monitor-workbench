"""unclassified 路由：/api/v1/unclassified。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.services.work_service import work_service

router = APIRouter(prefix="/api/v1/unclassified", tags=["unclassified"], dependencies=[Depends(require_admin)])


@router.get("", status_code=200)
def list_unclassified(
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    result = work_service.unclassified(db, page, limit)
    return ok(result.model_dump())
