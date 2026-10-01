"""A stable index row for one physical archive directory."""
from __future__ import annotations

import ntpath
import os

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.utils.timeutil import now_iso


def physical_directory_key(relative_directory: str) -> str:
    """Use the host filesystem's directory identity without changing display spelling."""
    normalized = relative_directory.replace("\\", "/")
    return ntpath.normcase(normalized) if os.name == "nt" else normalized


def _physical_directory_key_default(context) -> str:
    values = context.get_current_parameters()
    return physical_directory_key(values["relative_directory"])


class ArchiveEntry(Base):
    __tablename__ = "archive_entries"
    __table_args__ = (
        UniqueConstraint("root_key", "physical_directory_key", name="uq_archive_physical_directory"),
        Index("ix_archive_entries_work_id", "work_id"),
        Index("ix_archive_entries_platform_external", "platform", "external_id"),
        Index("ix_archive_entries_creator_group", "creator_id", "group_id"),
        Index("ix_archive_entries_published_at", "published_at"),
        Index("ix_archive_entries_downloaded_at", "downloaded_at"),
        Index("ix_archive_entries_check_status", "check_status"),
        Index("ix_archive_entries_sync_status", "sync_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    root_key: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_directory: Mapped[str] = mapped_column(Text, nullable=False)
    physical_directory_key: Mapped[str] = mapped_column(
        Text, nullable=False, default=_physical_directory_key_default
    )
    work_id: Mapped[int | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[int | None] = mapped_column(
        ForeignKey("creators.id", ondelete="SET NULL"), nullable=True
    )
    creator_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
    group_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    published_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_time_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_time_precision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    downloaded_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_time_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_time_precision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    metadata_checked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_status: Mapped[str] = mapped_column(String(20), nullable=False, default="needs_review")

    metadata_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    files_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)
