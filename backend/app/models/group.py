"""groups — 分组。"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.utils.timeutil import now_iso


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Group id={self.id} name={self.name!r}>"
