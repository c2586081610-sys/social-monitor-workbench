"""Audit trail for user-confirmed archive metadata edits."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.utils.timeutil import now_iso


class ArchiveRevision(Base):
    __tablename__ = "archive_revisions"
    __table_args__ = (
        Index("ix_archive_revisions_entry_changed", "archive_entry_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    archive_entry_id: Mapped[int] = mapped_column(
        ForeignKey("archive_entries.id", ondelete="CASCADE"), nullable=False
    )
    before_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    after_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    changed_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)

