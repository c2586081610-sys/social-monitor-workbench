"""tags 数据访问。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Tag, WorkTag


def get(db: Session, tag_id: int) -> Tag | None:
    return db.get(Tag, tag_id)


def get_by_name(db: Session, name: str) -> Tag | None:
    return db.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()


def list_tags(db: Session, kind: str | None = None) -> list[tuple[Tag, int]]:
    """返回 (Tag, work_count) 列表，按作品数降序。"""
    stmt = (
        select(Tag, func.count(WorkTag.work_id))
        .outerjoin(WorkTag, WorkTag.tag_id == Tag.id)
    )
    if kind:
        stmt = stmt.where(Tag.kind == kind)
    stmt = stmt.group_by(Tag.id).order_by(func.count(WorkTag.work_id).desc(), Tag.id)
    return [(tag, count) for tag, count in db.execute(stmt).all()]


def create(db: Session, name: str, kind: str = "small") -> Tag:
    tag = Tag(name=name, kind=kind)
    db.add(tag)
    db.flush()
    return tag


def link_work(db: Session, work_id: int, tag_id: int) -> None:
    db.add(WorkTag(work_id=work_id, tag_id=tag_id))
    db.flush()
