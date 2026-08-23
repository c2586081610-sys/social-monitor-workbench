"""works 数据访问（含幂等 upsert 与多条件过滤）。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Tag, Work, WorkTag


def get(db: Session, work_id: int) -> Work | None:
    return db.get(Work, work_id)


def get_by_platform_external(db: Session, platform: str, external_id: str) -> Work | None:
    stmt = select(Work).where(Work.platform == platform, Work.external_id == external_id)
    return db.execute(stmt).scalar_one_or_none()


def upsert(db: Session, platform: str, external_id: str, **fields) -> Work:
    """按 (platform, external_id) 幂等 upsert：存在则更新，否则新建。"""
    work = get_by_platform_external(db, platform, external_id)
    if work is None:
        work = Work(platform=platform, external_id=external_id, **fields)
        db.add(work)
    else:
        for key, value in fields.items():
            setattr(work, key, value)
    db.flush()
    return work


def create(db: Session, **fields) -> Work:
    work = Work(**fields)
    db.add(work)
    db.flush()
    return work


def update(db: Session, work: Work, **fields) -> Work:
    for key, value in fields.items():
        setattr(work, key, value)
    db.flush()
    return work


def _apply_filters(stmt, *, group_id, creator_id, tag, platform, status, source_type, unclassified, q):
    if group_id is not None:
        stmt = stmt.where(Work.group_id == group_id)
    if creator_id is not None:
        stmt = stmt.where(Work.creator_id == creator_id)
    if platform:
        stmt = stmt.where(Work.platform == platform)
    if status:
        stmt = stmt.where(Work.status == status)
    if source_type:
        stmt = stmt.where(Work.source_type == source_type)
    if unclassified:
        stmt = stmt.where(Work.group_id.is_(None))
    if q:
        stmt = stmt.where(Work.title.ilike(f"%{q}%"))
    if tag:
        stmt = stmt.join(WorkTag, WorkTag.work_id == Work.id).join(Tag, Tag.id == WorkTag.tag_id).where(
            Tag.name == tag
        )
    return stmt


def list_works(
    db: Session,
    *,
    group_id: int | None = None,
    creator_id: int | None = None,
    tag: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    unclassified: bool = False,
    q: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Work], int]:
    base = _apply_filters(
        select(Work),
        group_id=group_id,
        creator_id=creator_id,
        tag=tag,
        platform=platform,
        status=status,
        source_type=source_type,
        unclassified=unclassified,
        q=q,
    )
    total = db.execute(
        _apply_filters(
            select(func.count()).select_from(Work),
            group_id=group_id,
            creator_id=creator_id,
            tag=tag,
            platform=platform,
            status=status,
            source_type=source_type,
            unclassified=unclassified,
            q=q,
        )
    ).scalar_one()
    items = db.execute(
        base.order_by(Work.published_at.desc().nullslast(), Work.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).scalars().all()
    return list(items), total


def list_unclassified(db: Session, page: int = 1, limit: int = 20) -> tuple[list[Work], int]:
    """待分类池：group_id 为空 且 状态在 (UNCLASSIFIED, NOTE_GENERATING, DONE)。"""
    statuses = ["UNCLASSIFIED", "NOTE_GENERATING", "DONE"]
    base = select(Work).where(Work.group_id.is_(None), Work.status.in_(statuses))
    total = db.execute(
        select(func.count()).select_from(Work).where(
            Work.group_id.is_(None), Work.status.in_(statuses)
        )
    ).scalar_one()
    items = db.execute(
        base.order_by(Work.id.desc()).offset((page - 1) * limit).limit(limit)
    ).scalars().all()
    return list(items), total


def list_by_creator(db: Session, creator_id: int, page: int = 1, limit: int = 20) -> tuple[list[Work], int]:
    return list_works(db, creator_id=creator_id, page=page, limit=limit)


def recent_by_creator(db: Session, creator_id: int, limit: int = 5) -> list[Work]:
    stmt = (
        select(Work)
        .where(Work.creator_id == creator_id)
        .order_by(Work.published_at.desc().nullslast(), Work.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_by_tag(db: Session, tag_id: int, page: int = 1, limit: int = 20) -> tuple[list[Work], int]:
    base = (
        select(Work)
        .join(WorkTag, WorkTag.work_id == Work.id)
        .where(WorkTag.tag_id == tag_id)
    )
    total = db.execute(
        select(func.count())
        .select_from(Work)
        .join(WorkTag, WorkTag.work_id == Work.id)
        .where(WorkTag.tag_id == tag_id)
    ).scalar_one()
    items = db.execute(
        base.order_by(Work.id.desc()).offset((page - 1) * limit).limit(limit)
    ).scalars().all()
    return list(items), total


def clear_work_tags(db: Session, work_id: int) -> None:
    db.query(WorkTag).filter(WorkTag.work_id == work_id).delete(synchronize_session=False)
    db.flush()


def count_frames_fallback(_db: Session, _work: Work) -> int:
    """占位（真实帧数由 service 读 manifest 计算），此处不实现业务。"""
    return 0
