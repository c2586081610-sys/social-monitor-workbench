"""creators 路由：/api/v1/creators*。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.schemas.creator import CreatorCreate, CreatorUpdate
from app.schemas.work import WorkPage
from app.services.creator_service import creator_service
from app.services.work_service import work_service

router = APIRouter(prefix="/api/v1/creators", tags=["creators"], dependencies=[Depends(require_admin)])


@router.get("", status_code=200)
def list_creators(
    db: Session = Depends(get_db),
    group_id: int | None = Query(default=None, ge=1),
    platform: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
):
    result = creator_service.list(db, group_id, platform, q, page, limit)
    return ok(result.model_dump())


@router.post("", status_code=201)
def create_creator(payload: CreatorCreate, db: Session = Depends(get_db)):
    creator = creator_service.create(db, payload)
    return ok(creator.model_dump())


@router.get("/{creator_id}", status_code=200)
def get_creator(creator_id: int, db: Session = Depends(get_db)):
    creator = creator_service.get(db, creator_id)
    return ok(creator.model_dump())


@router.patch("/{creator_id}", status_code=200)
def update_creator(creator_id: int, payload: CreatorUpdate, db: Session = Depends(get_db)):
    creator = creator_service.update(db, creator_id, payload)
    return ok(creator.model_dump())


@router.delete("/{creator_id}", status_code=200)
def delete_creator(creator_id: int, db: Session = Depends(get_db)):
    return ok(creator_service.delete(db, creator_id))


@router.get("/{creator_id}/works", status_code=200)
def list_creator_works(
    creator_id: int,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
):
    result: WorkPage = work_service.list_by_creator(db, creator_id, page, limit)
    return ok(result.model_dump())
