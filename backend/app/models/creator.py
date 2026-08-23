"""creators — 博主（四平台）。UNIQUE(platform, external_id) 幂等。"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.utils.timeutil import now_iso


class Creator(Base):
    __tablename__ = "creators"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_creators_platform_external"),
        CheckConstraint(
            "platform IN ('douyin','bilibili','xhs','twitter','wechat')",
            name="ck_creators_platform",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_url: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[int] = mapped_column(nullable=False, default=1)
    last_poll_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_work_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default=now_iso, onupdate=now_iso)

    group = relationship("Group", lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Creator id={self.id} platform={self.platform} name={self.name!r}>"
