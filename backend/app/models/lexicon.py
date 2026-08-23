"""lexicon — 词库（语义对齐抽帧驱动，B4 机制细化预留）。"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.utils.timeutil import now_iso


class LexiconEntry(Base):
    __tablename__ = "lexicon"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="increase")
    weight: Mapped[float] = mapped_column(nullable=False, default=1.0)
    enabled: Mapped[int] = mapped_column(nullable=False, default=1)
    platform_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LexiconEntry id={self.id} term={self.term!r} action={self.action}>"
