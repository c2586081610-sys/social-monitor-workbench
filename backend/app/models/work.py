"""works — 作品（核心状态机）。UNIQUE(platform, external_id) 跨来源幂等去重。"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.utils.timeutil import now_iso


class Work(Base):
    __tablename__ = "works"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_works_platform_external"),
        Index("ix_works_status", "status"),
        Index("ix_works_group_id", "group_id"),
        Index("ix_works_creator_id", "creator_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    creator_id: Mapped[int | None] = mapped_column(
        ForeignKey("creators.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="monitor")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="NEW")
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    frame_manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    creator = relationship("Creator", lazy="joined")
    group = relationship("Group", lazy="joined")
    tags = relationship("Tag", secondary="work_tags", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Work id={self.id} platform={self.platform} status={self.status}>"
