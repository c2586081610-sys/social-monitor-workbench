"""groups 路由：/api/v1/groups*。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.schemas.group import GroupCreate, GroupUpdate
from app.services.group_service import group_service

router = APIRouter(prefix="/api/v1/groups", tags=["groups"], dependencies=[Depends(require_admin)])


@router.get("", status_code=200)
def list_groups(db: Session = Depends(get_db)):
    return ok({"items": [g.model_dump() for g in group_service.list(db)]})


@router.post("", status_code=201)
def create_group(payload: GroupCreate, db: Session = Depends(get_db)):
    group = group_service.create(db, payload.name)
    return ok(group.model_dump())


@router.patch("/{group_id}", status_code=200)
def rename_group(group_id: int, payload: GroupUpdate, db: Session = Depends(get_db)):
    group = group_service.rename(db, group_id, payload.name)
    return ok(group.model_dump())


@router.delete("/{group_id}", status_code=200)
def delete_group(group_id: int, db: Session = Depends(get_db)):
    return ok(group_service.delete(db, group_id))
