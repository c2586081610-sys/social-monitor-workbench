-- SQLite 初始化迁移（等价于 ORM create_all 生成结构；实际以 create_all 为准）
-- 说明：MVP 采用 SQLAlchemy Base.metadata.create_all 自动建表，本文件为契约存档。
-- 若需增量迁移，请使用 alembic 或在此追加手写 SQL。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    platform TEXT NOT NULL CHECK (platform IN ('douyin','bilibili','xhs','twitter','wechat')),
    name TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    external_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_poll_at TEXT,
    last_work_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, external_id)
);

CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER REFERENCES creators(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    source_type TEXT NOT NULL DEFAULT 'monitor',
    status TEXT NOT NULL DEFAULT 'NEW',
    task_id TEXT,
    media_path TEXT,
    transcript_path TEXT,
    frame_manifest_path TEXT,
    note_path TEXT,
    group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS ix_works_status ON works(status);
CREATE INDEX IF NOT EXISTS ix_works_group_id ON works(group_id);
CREATE INDEX IF NOT EXISTS ix_works_creator_id ON works(creator_id);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'small',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_tags (
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (work_id, tag_id)
);

CREATE INDEX IF NOT EXISTS ix_work_tags_tag_id ON work_tags(tag_id);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (work_id, stage)
);

CREATE TABLE IF NOT EXISTS lexicon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL DEFAULT 'increase',
    weight REAL NOT NULL DEFAULT 1.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    platform_scope TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cookies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    last_checked_at TEXT,
    expires_at TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS poll_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
