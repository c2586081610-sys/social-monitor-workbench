"""tasks — 阶段级任务（一作品多阶段，UNIQUE(work_id, stage) 重试更新同行）。"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.utils.timeutil import now_iso


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("work_id", "stage", name="uq_tasks_work_stage"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False)  # parse/download/transcribe/frames/note
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task work={self.work_id} stage={self.stage} status={self.status}>"
