"""SQLAlchemy engine/session + 建表与目录初始化（幂等）。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{settings.database_path}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_conn, _record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

_COOKIE_PLATFORMS = ["douyin", "bilibili", "xhs", "twitter"]


def _ensure_dirs() -> None:
    for d in (settings.media_root, settings.obsidian_root, settings.pending_dir, settings.trigger_dir):
        Path(d).mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    """建表 + 种子 cookie 健康度行 + 创建存储目录。幂等，聚合 API 与监控层共用。"""
    _ensure_dirs()
    # 延迟导入避免循环依赖（models 依赖 db.Base）
    from app.models import (  # noqa: F401  确保全部表注册到 metadata
        CookieHealth,
    )

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        from app.repositories.health_repo import upsert_cookie

        for platform in _COOKIE_PLATFORMS:
            upsert_cookie(db, platform=platform, status="UNKNOWN", note=None)
        db.commit()
