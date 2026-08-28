"""SQLAlchemy engine/session + 建表与目录初始化（幂等）。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# URI 模式连接：本机环境普通 connect 的写打开会被 WorkBuddy 沙盒拦截为只读
# （实测 sqlite:///path 打开 CREATE TABLE 报 readonly；file:...?mode=rwc + uri=true 正常读写）。
engine = create_engine(
    f"sqlite:///file:{settings.database_path.as_posix()}?mode=rwc&uri=true",
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


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """幂等加列：PRAGMA table_info 检查列不存在时 ALTER TABLE ADD COLUMN（v0.4 迁移）。"""
    cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    if column not in cols:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    """建表 + 种子 cookie 健康度行 + 创建存储目录。幂等，聚合 API 与监控层共用。"""
    _ensure_dirs()
    # 延迟导入避免循环依赖（models 依赖 db.Base）
    from app.models import (  # noqa: F401  确保全部表注册到 metadata
        CookieHealth,
    )

    Base.metadata.create_all(bind=engine)

    # v0.4 轻量迁移：works 新增 content_type / media_urls（幂等，已存在则跳过）
    with engine.begin() as conn:
        _ensure_column(conn, "works", "content_type", "VARCHAR(10) NOT NULL DEFAULT 'video'")
        _ensure_column(conn, "works", "media_urls", "TEXT")
        # v0.5 迁移：lexicon 新增 category（兴趣区间：finance/ai/fitness/business/general）
        _ensure_column(conn, "lexicon", "category", "VARCHAR(30)")
        # v0.6 迁移：poll_logs 新增 new_works（本次爬取检测到的新作品数，默认 0）
        _ensure_column(conn, "poll_logs", "new_works", "INTEGER NOT NULL DEFAULT 0")
        # v0.6 迁移：works 新增 cover_url（作品封面图，前端列表展示）
        _ensure_column(conn, "works", "cover_url", "TEXT")

    with SessionLocal() as db:
        from app.repositories.health_repo import upsert_cookie

        for platform in _COOKIE_PLATFORMS:
            upsert_cookie(db, platform=platform, status="UNKNOWN", note=None)
        db.commit()
