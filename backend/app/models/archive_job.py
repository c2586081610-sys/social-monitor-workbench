"""Durable archive scan/refresh/sync work, independent of media pipeline Tasks."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.utils.timeutil import now_iso


class ArchiveJob(Base):
    __tablename__ = "archive_jobs"
    __table_args__ = (
        Index("ix_archive_jobs_claim", "status", "lease_expires_at", "created_at"),
        Index("ix_archive_jobs_root_directory", "root_key", "relative_directory"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    root_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    relative_directory: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_entries.id", ondelete="SET NULL"), nullable=True
    )
    cursor: Mapped[dict] = mapped_column("cursor_json", JSON, nullable=False, default=dict)
    statistics: Mapped[dict] = mapped_column("statistics_json", JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)
    started_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
