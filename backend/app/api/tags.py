"""tags 路由：/api/v1/tags*。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.services.tag_service import tag_service

router = APIRouter(prefix="/api/v1/tags", tags=["tags"], dependencies=[Depends(require_admin)])


@router.get("", status_code=200)
def list_tags(
    db: Session = Depends(get_db),
    kind: str | None = Query(default=None),
):
    return ok({"items": [t.model_dump() for t in tag_service.list(db, kind)]})


@router.get("/{tag_name}/works", status_code=200)
def list_works_by_tag(
    tag_name: str,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    result = tag_service.works(db, tag_name, page, limit)
    return ok(result.model_dump())
