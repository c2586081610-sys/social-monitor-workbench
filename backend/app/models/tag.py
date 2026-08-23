"""tags — 双层标签（big 大标签 / small 小标签）。"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.utils.timeutil import now_iso


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="small")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    works = relationship("Work", secondary="work_tags", back_populates="tags", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tag id={self.id} name={self.name!r} kind={self.kind}>"
