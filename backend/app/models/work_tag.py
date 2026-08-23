"""work_tags — 作品×标签 多对多关联表。"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WorkTag(Base):
    __tablename__ = "work_tags"
    __table_args__ = (Index("ix_work_tags_tag_id", "tag_id"),)

    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
