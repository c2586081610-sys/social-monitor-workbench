"""lexicon 词库数据访问。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LexiconEntry


def get(db: Session, entry_id: int) -> LexiconEntry | None:
    return db.get(LexiconEntry, entry_id)


def get_by_term(db: Session, term: str) -> LexiconEntry | None:
    return db.execute(select(LexiconEntry).where(LexiconEntry.term == term)).scalar_one_or_none()


def list_entries(db: Session) -> list[LexiconEntry]:
    stmt = select(LexiconEntry).order_by(LexiconEntry.id)
    return list(db.execute(stmt).scalars().all())


def create(db: Session, **fields) -> LexiconEntry:
    entry = LexiconEntry(**fields)
    db.add(entry)
    db.flush()
    return entry


def update(db: Session, entry: LexiconEntry, **fields) -> LexiconEntry:
    for key, value in fields.items():
        setattr(entry, key, value)
    db.flush()
    return entry


def delete(db: Session, entry: LexiconEntry) -> None:
    db.delete(entry)
    db.flush()
