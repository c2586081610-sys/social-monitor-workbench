"""creators 数据访问。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Creator


def get(db: Session, creator_id: int) -> Creator | None:
    return db.get(Creator, creator_id)


def get_by_platform_external(db: Session, platform: str, external_id: str) -> Creator | None:
    stmt = select(Creator).where(
        Creator.platform == platform,
        Creator.external_id == external_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def list_creators(
    db: Session,
    group_id: int | None = None,
    platform: str | None = None,
    q: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Creator], int]:
    filters = []
    if group_id is not None:
        filters.append(Creator.group_id == group_id)
    if platform:
        filters.append(Creator.platform == platform)
    if q:
        filters.append(Creator.name.ilike(f"%{q}%"))

    base = select(Creator).where(*filters)
    total = db.execute(select(func.count()).select_from(Creator).where(*filters)).scalar_one()
    items = (
        db.execute(
            base.order_by(Creator.id.desc()).offset((page - 1) * limit).limit(limit)
        )
        .scalars()
        .all()
    )
    return list(items), total


def create(db: Session, **fields) -> Creator:
    creator = Creator(**fields)
    db.add(creator)
    db.flush()
    return creator


def update(db: Session, creator: Creator, **fields) -> Creator:
    for key, value in fields.items():
        setattr(creator, key, value)
    db.flush()
    return creator


def delete(db: Session, creator: Creator) -> None:
    db.delete(creator)
    db.flush()


def count_by_group(db: Session, group_id: int) -> int:
    return db.execute(
        select(func.count()).select_from(Creator).where(Creator.group_id == group_id)
    ).scalar_one()


def move_all_to_ungrouped(db: Session, group_id: int) -> int:
    """把某分组下博主移入未分组，返回移动数。"""
    stmt = select(Creator).where(Creator.group_id == group_id)
    creators = db.execute(stmt).scalars().all()
    for creator in creators:
        creator.group_id = None
    db.flush()
    return len(creators)
