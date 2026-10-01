"""Persistence and public contract tests for the local archive foundation."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core import db as db_module
from app.core.config import _archive_root_paths, archive_root_policy, settings
from app.models import ArchiveEntry, ArchiveJob, ArchiveRevision, Work
from app.repositories import archive_repo, work_repo
from app.schemas.archive import (
    ArchiveEntrySchema,
    ArchiveFilters,
    ArchiveJobSchema,
    ArchiveMetadataPatch,
    ArchivePolicy,
)
from app.schemas.work import Work as WorkSchema


def _entry(db, *, root_key="media", relative_directory="archive/test", **fields):
    values = {
        "platform": "bilibili",
        "external_id": "BV1-test",
        "title": "归档作品",
        "url": "https://www.bilibili.com/video/BV1-test",
    }
    values.update(fields)
    return archive_repo.upsert_entry(
        db,
        root_key=root_key,
        relative_directory=relative_directory,
        **values,
    )


def _work(db, *, external_id="archive-work"):
    work = work_repo.create(
        db,
        platform="bilibili",
        external_id=external_id,
        title=f"作品 {external_id}",
        url=f"https://www.bilibili.com/video/{external_id}",
        source_type="manual",
        status="NEW",
    )
    db.commit()
    return work


def test_old_works_table_migrates_idempotently_and_preserves_existing_values(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{database_path}")
    with legacy_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE works (
                id INTEGER PRIMARY KEY,
                creator_id INTEGER,
                platform VARCHAR(20) NOT NULL,
                external_id VARCHAR(200) NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT,
                source_type VARCHAR(20) NOT NULL,
                content_type VARCHAR(10) NOT NULL DEFAULT 'video',
                media_urls TEXT,
                cover_url TEXT,
                status VARCHAR(30) NOT NULL,
                task_id VARCHAR(100),
                media_path TEXT,
                transcript_path TEXT,
                frame_manifest_path TEXT,
                note_path TEXT,
                group_id INTEGER,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO works (
                id, platform, external_id, title, url, source_type, status,
                created_at, updated_at, published_at, media_path
            ) VALUES (
                41, 'bilibili', 'legacy-BV', '旧作品', 'https://example.test/legacy',
                'monitor', 'DONE', '2026-08-01T00:00:00Z', '2026-08-02T00:00:00Z',
                '2026-07-31T16:00:00Z', '博主/旧目录'
            )
        """))

    monkeypatch.setattr(db_module, "engine", legacy_engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=legacy_engine, expire_on_commit=False))

    db_module.init_db()
    db_module.init_db()

    with legacy_engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(works)"))}
        assert {"downloaded_at", "download_time_source"} <= columns
        row = conn.execute(
            text("SELECT id, title, published_at, media_path, downloaded_at, download_time_source FROM works WHERE id=41")
        ).one()
    assert tuple(row[:4]) == (41, "旧作品", "2026-07-31T16:00:00Z", "博主/旧目录")
    assert row.downloaded_at is None
    assert row.download_time_source is None
    legacy_engine.dispose()


def test_new_work_download_times_are_nullable_by_default(db):
    work = _work(db)
    assert work.downloaded_at is None
    assert work.download_time_source is None
    assert db.get(Work, work.id).downloaded_at is None
    response = WorkSchema.model_validate(work)
    assert response.downloaded_at is None
    assert response.download_time_source is None


def test_physical_path_upsert_is_idempotent_and_database_key_is_unique(db):
    first = _entry(db, relative_directory="creator/video")
    first_id = first.id
    second = _entry(
        db,
        relative_directory=r"creator\.\video",
        title="补齐后的标题",
        check_status="verified",
    )
    db.commit()

    assert second.id == first_id
    assert second.title == "补齐后的标题"
    assert db.query(ArchiveEntry).filter_by(root_key="media", relative_directory="creator/video").count() == 1
    response = ArchiveEntrySchema.model_validate(second)
    assert response.metadata == {}
    assert response.files == []

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ArchiveEntry(
                root_key="media",
                relative_directory="creator/video",
                platform="bilibili",
                title="重复物理路径",
            ))
            db.flush()


def test_archive_list_filters_use_beijing_calendar_days_and_unknown_time_rules(db):
    root = "media"
    title = "beijing-date-case"
    _entry(db, relative_directory="boundary/before", published_at="2026-09-29T15:59:59Z", title=title)
    _entry(db, relative_directory="boundary/start", published_at="2026-09-29T16:00:00Z", title=title)
    _entry(db, relative_directory="boundary/end", published_at="2026-09-30T15:59:59Z", title=title)
    _entry(db, relative_directory="boundary/after", published_at="2026-09-30T16:00:00Z", title=title)
    _entry(db, relative_directory="boundary/unknown", published_at=None, title=title)
    _entry(
        db,
        relative_directory="boundary/downloaded-time",
        published_at="2026-09-28T00:00:00Z",
        downloaded_at="2026-09-29T16:00:00Z",
        title=title,
    )

    base = ArchiveFilters(
        root_key=root,
        platform="bilibili",
        q=title,
        time_field="published_at",
        date_from=date(2026, 9, 30),
        date_to=date(2026, 9, 30),
        limit=20,
    )
    rows, total = archive_repo.list_entries(db, filters=base)
    paths = {item.relative_directory for item in rows}
    assert total == 2
    assert paths == {"boundary/start", "boundary/end"}

    downloaded_filters = base.model_copy(update={"time_field": "downloaded_at"})
    rows, total = archive_repo.list_entries(db, filters=downloaded_filters)
    assert total == 1
    assert rows[0].relative_directory == "boundary/downloaded-time"

    with_unknown = base.model_copy(update={"include_unknown_time": True})
    rows, total = archive_repo.list_entries(db, filters=with_unknown)
    assert total == 3
    assert "boundary/unknown" in {item.relative_directory for item in rows}

    unknown_only = base.model_copy(update={"unknown_time_only": True})
    rows, total = archive_repo.list_entries(db, filters=unknown_only)
    assert total == 1
    assert rows[0].relative_directory == "boundary/unknown"


def test_archive_filter_rejects_reversed_dates_and_unknown_enums():
    with pytest.raises(ValueError):
        ArchiveFilters(date_from="2026-10-02", date_to="2026-10-01")
    with pytest.raises(ValueError):
        ArchiveFilters(platform="not-a-platform")
    with pytest.raises(ValueError):
        ArchiveFilters(check_status="looks-good")
    with pytest.raises(ValueError):
        ArchiveFilters(time_field="created_at")
    with pytest.raises(ValueError):
        ArchiveMetadataPatch(title=None)
    with pytest.raises(ValueError):
        ArchiveMetadataPatch(downloaded_at="2026-10-01T00:00:00Z")


def test_filtered_export_uses_same_filters_without_page_limit(db):
    for index in range(215):
        _entry(
            db,
            relative_directory=f"bulk/{index:03d}",
            platform="wechat",
            external_id=f"mp-{index}",
            title=f"合集目标 {index}",
        )
    for index in range(7):
        _entry(
            db,
            relative_directory=f"bulk/other-{index}",
            platform="douyin",
            external_id=f"dy-{index}",
            title=f"合集目标 排除 {index}",
        )
    db.commit()

    filters = ArchiveFilters(platform="wechat", q="合集目标", root_key="media", page=1, limit=20)
    items, total = archive_repo.list_entries(db, filters=filters)
    exported = archive_repo.export_entries(db, filters=filters)

    assert len(items) == 20
    assert total == 215
    assert len(exported) == 215
    assert {row.platform for row in exported} == {"wechat"}


def test_work_reference_returns_every_physical_archive_copy(db):
    work = _work(db, external_id="archive-multipath")
    _entry(db, relative_directory="copy-one", work_id=work.id)
    _entry(db, relative_directory="copy-two", work_id=work.id)
    db.commit()

    assert {row.relative_directory for row in archive_repo.list_by_work(db, work.id)} == {
        "copy-one",
        "copy-two",
    }
    rows, total = archive_repo.list_entries(
        db,
        filters=ArchiveFilters(work_id=[work.id], limit=20),
    )
    assert total == 2
    assert {row.relative_directory for row in rows} == {"copy-one", "copy-two"}


def test_archive_jobs_persist_progress_and_claim_one_unexpired_lease(db):
    job = archive_repo.create_job(
        db,
        job_type="scan",
        root_key="media",
        relative_directory="history",
    )
    refresh = archive_repo.create_job(db, job_type="refresh", root_key="media", relative_directory="history/item")
    sync = archive_repo.create_job(db, job_type="sync", root_key="media", relative_directory="history/item")
    archive_repo.update_job(db, refresh, status="completed")
    archive_repo.update_job(db, sync, status="completed")
    db.commit()
    assert {job.job_type, refresh.job_type, sync.job_type} == {"scan", "refresh", "sync"}
    assert ArchiveJobSchema.model_validate(job).id == job.id

    now = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    claimed = archive_repo.claim_next_job(db, worker_id="worker-a", lease_seconds=120, now=now)
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.lease_owner == "worker-a"
    db.commit()

    with db_module.SessionLocal() as second_session:
        duplicate_claim = archive_repo.claim_next_job(
            second_session,
            worker_id="worker-b",
            lease_seconds=120,
            now=now + timedelta(seconds=30),
        )
        assert duplicate_claim is None

    archive_repo.update_job(
        db,
        claimed,
        status="partial",
        cursor={"last_directory": "history/item"},
        statistics={"indexed": 2, "conflict": 1},
        error="one directory needs review",
    )
    db.commit()
    persisted = archive_repo.get_job(db, job.id)
    assert persisted.status == "partial"
    assert persisted.cursor == {"last_directory": "history/item"}
    assert persisted.statistics == {"indexed": 2, "conflict": 1}
    assert persisted.error == "one directory needs review"

    expired = archive_repo.create_job(
        db,
        job_type="scan",
        root_key="media",
        relative_directory="recovery",
    )
    archive_repo.update_job(
        db,
        expired,
        status="running",
        lease_owner="stopped-worker",
        lease_expires_at="2026-09-30T23:59:00Z",
    )
    db.commit()
    recovered = archive_repo.claim_next_job(
        db,
        worker_id="worker-c",
        lease_seconds=120,
        now=now,
    )
    assert recovered is not None
    assert recovered.id == expired.id
    assert recovered.lease_owner == "worker-c"


def test_archive_revision_keeps_manual_before_after_values_and_source(db):
    entry = _entry(db, relative_directory="revision/item", title="原标题", published_time_source="platform")
    db.commit()

    revision = archive_repo.create_revision(
        db,
        archive_entry_id=entry.id,
        before_values={"title": "原标题", "published_time_source": "platform"},
        after_values={"title": "人工修正标题", "published_time_source": "manual"},
        source="manual",
    )
    db.commit()

    persisted = db.get(ArchiveRevision, revision.id)
    assert persisted.archive_entry_id == entry.id
    assert persisted.before_values["title"] == "原标题"
    assert persisted.after_values["title"] == "人工修正标题"
    assert persisted.source == "manual"


def test_policy_exposes_contract_and_five_platform_labels_without_machine_paths():
    policy_data = archive_root_policy()
    policy = ArchivePolicy.model_validate(policy_data)

    assert policy.timezone == "Asia/Shanghai"
    assert policy.directory_template
    assert set(policy.information_files) == {"作品信息.csv", "作品信息.json", "作品信息.md"}
    assert {item.value for item in policy.platforms} == {"douyin", "bilibili", "xhs", "twitter", "wechat"}
    assert {item.root_key for item in policy.roots} >= {"media", "fitness"}
    assert all(item.label and isinstance(item.configured, bool) for item in policy.roots)
    assert all(set(item.model_dump()) == {"root_key", "label", "configured"} for item in policy.roots)
    assert all("path" not in item.model_dump() for item in policy.roots)


def test_optional_local_root_mapping_is_server_only_and_keeps_media_root_authoritative(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    fitness_root = tmp_path / "private-fitness"
    extra_root = tmp_path / "private-library"
    monkeypatch.setenv(
        "ARCHIVE_ROOTS",
        json.dumps({
            "media": str(tmp_path / "ignored-media-override"),
            "fitness": str(fitness_root),
            "library": str(extra_root),
        }),
    )

    roots = _archive_root_paths(media_root, tmp_path)
    assert roots["media"] == media_root
    assert roots["fitness"] == fitness_root.resolve()
    assert roots["library"] == extra_root.resolve()

    monkeypatch.setattr(settings, "archive_root_paths", roots)
    public_policy = archive_root_policy()
    assert {item["root_key"] for item in public_policy["roots"]} == {"media", "fitness", "library"}
    assert str(fitness_root) not in repr(public_policy)
    assert str(extra_root) not in repr(public_policy)
