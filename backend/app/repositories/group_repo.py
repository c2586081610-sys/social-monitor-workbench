"""groups 数据访问。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Creator, Group, Work


def get(db: Session, group_id: int) -> Group | None:
    return db.get(Group, group_id)


def get_by_name(db: Session, name: str) -> Group | None:
    return db.execute(select(Group).where(Group.name == name)).scalar_one_or_none()


def list_groups(db: Session) -> list[tuple[Group, int]]:
    """返回 (Group, creator_count) 列表。"""
    stmt = (
        select(Group, func.count(Creator.id))
        .outerjoin(Creator, Creator.group_id == Group.id)
        .group_by(Group.id)
        .order_by(Group.id)
    )
    rows = db.execute(stmt).all()
    return [(group, count) for group, count in rows]


def create(db: Session, name: str) -> Group:
    group = Group(name=name)
    db.add(group)
    db.flush()
    return group


def rename(db: Session, group: Group, name: str) -> Group:
    group.name = name
    db.flush()
    return group


def delete(db: Session, group: Group) -> None:
    db.delete(group)
    db.flush()


def clear_works_group(db: Session, group_id: int) -> int:
    """删除分组后组内作品移入未分组（作品保留），返回作品数。"""
    works = db.execute(select(Work).where(Work.group_id == group_id)).scalars().all()
    for work in works:
        work.group_id = None
    db.flush()
    return len(works)
