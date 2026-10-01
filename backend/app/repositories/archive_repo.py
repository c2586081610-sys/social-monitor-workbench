"""Database operations for physical archive rows, filters, audit history and leases."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ArchiveEntry, ArchiveJob, ArchiveRevision
from app.models.archive_entry import physical_directory_key
from app.schemas.archive import ArchiveFilters
from app.utils.timeutil import now_iso


_JOB_TYPES = {"scan", "refresh", "sync"}
_JOB_STATUSES = {"queued", "running", "completed", "partial", "failed"}
_EDITABLE_ENTRY_FIELDS = {
    "work_id", "platform", "external_id", "title", "url",
    "creator_id", "creator_label", "group_id", "group_label",
    "published_at", "published_time_source", "published_time_precision",
    "downloaded_at", "download_time_source", "download_time_precision",
    "metadata_checked_at", "check_status", "metadata_version", "metadata_json",
    "files_json", "sync_status", "sync_error", "synced_at",
}
_EDITABLE_JOB_FIELDS = {
    "status", "cursor", "statistics", "error", "lease_owner", "lease_expires_at",
    "started_at", "completed_at",
}


def _require_root_key(root_key: str) -> str:
    if not isinstance(root_key, str) or root_key not in settings.archive_root_paths:
        raise ValueError(f"Unknown archive root key: {root_key!r}")
    return root_key


def normalize_relative_directory(relative_directory: str) -> str:
    """Canonicalize a stored path and reject absolute or parent-traversal paths."""
    if not isinstance(relative_directory, str) or not relative_directory.strip():
        raise ValueError("relative_directory must be a non-empty relative path")
    raw = relative_directory.strip().replace("\\", "/")
    if raw.startswith("/") or PureWindowsPath(raw).is_absolute() or PureWindowsPath(raw).drive:
        raise ValueError("relative_directory must not be absolute")
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("relative_directory must not contain parent traversal")
        parts.append(part)
    if not parts:
        raise ValueError("relative_directory must identify a directory below its root")
    return PurePosixPath(*parts).as_posix()


def get_entry(db: Session, archive_id: int) -> ArchiveEntry | None:
    return db.get(ArchiveEntry, archive_id)


def get_entry_by_path(db: Session, root_key: str, relative_directory: str) -> ArchiveEntry | None:
    _require_root_key(root_key)
    relative = normalize_relative_directory(relative_directory)
    stmt = select(ArchiveEntry).where(
        ArchiveEntry.root_key == root_key,
        ArchiveEntry.physical_directory_key == physical_directory_key(relative),
    )
    return db.execute(stmt).scalar_one_or_none()


def upsert_entry(
    db: Session,
    *,
    root_key: str,
    relative_directory: str,
    **fields: Any,
) -> ArchiveEntry:
    """Upsert by physical directory identity; never merges by title or platform ID."""
    _require_root_key(root_key)
    relative = normalize_relative_directory(relative_directory)
    aliases = {"metadata": "metadata_json", "files": "files_json"}
    values = {aliases.get(key, key): value for key, value in fields.items()}
    unknown = set(values) - _EDITABLE_ENTRY_FIELDS
    if unknown:
        raise ValueError(f"Unsupported archive entry fields: {', '.join(sorted(unknown))}")

    for key in ("title", "platform"):
        if key in values and not values[key]:
            raise ValueError(f"archive entry {key} must not be empty")

    existing = None
    identity_values = {}
    if "title" not in values or "platform" not in values:
        existing = get_entry_by_path(db, root_key, relative)
    if existing is None:
        if not values.get("title") or not values.get("platform"):
            raise ValueError("new archive entries require platform and title")
        identity_values = {"title": values["title"], "platform": values["platform"]}
    else:
        identity_values = {
            "title": values.get("title", existing.title),
            "platform": values.get("platform", existing.platform),
        }

    now = now_iso()
    insert_values = {
        "root_key": root_key,
        "relative_directory": relative,
        "physical_directory_key": physical_directory_key(relative),
        "check_status": "needs_review",
        "metadata_version": 1,
        "metadata_json": {},
        "files_json": [],
        "sync_status": "pending",
        "created_at": now,
        "updated_at": now,
        **identity_values,
        **values,
    }
    insert = sqlite_insert(ArchiveEntry).values(**insert_values)
    update_values = {key: insert.excluded[key] for key in values}
    update_values["updated_at"] = now
    statement = (
        insert.on_conflict_do_update(
            index_elements=[ArchiveEntry.root_key, ArchiveEntry.physical_directory_key],
            set_=update_values,
        )
        .returning(ArchiveEntry.id)
    )
    archive_id = db.execute(statement).scalar_one()
    return db.get(ArchiveEntry, archive_id, populate_existing=True)


def list_by_work(db: Session, work_id: int) -> list[ArchiveEntry]:
    """Return every physical archive copy linked to one pipeline Work."""
    stmt = (
        select(ArchiveEntry)
        .where(ArchiveEntry.work_id == work_id)
        .order_by(ArchiveEntry.root_key, ArchiveEntry.relative_directory, ArchiveEntry.id)
    )
    return list(db.execute(stmt).scalars().all())


def _coerce_filters(filters: ArchiveFilters | Mapping[str, Any] | None) -> ArchiveFilters:
    if filters is None:
        return ArchiveFilters()
    if isinstance(filters, ArchiveFilters):
        return filters
    return ArchiveFilters.model_validate(dict(filters))


def _utc_day_boundary(day: date) -> str:
    beijing = datetime.combine(day, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
    return beijing.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _filter_conditions(filters: ArchiveFilters) -> list[Any]:
    conditions = []
    if filters.platform is not None:
        conditions.append(ArchiveEntry.platform == filters.platform)
    if filters.creator_id is not None:
        conditions.append(ArchiveEntry.creator_id == filters.creator_id)
    if filters.group_id is not None:
        conditions.append(ArchiveEntry.group_id == filters.group_id)
    if filters.work_id is not None:
        if isinstance(filters.work_id, list):
            conditions.append(ArchiveEntry.work_id.in_(filters.work_id))
        else:
            conditions.append(ArchiveEntry.work_id == filters.work_id)
    if filters.root_key is not None:
        _require_root_key(filters.root_key)
        conditions.append(ArchiveEntry.root_key == filters.root_key)
    if filters.check_status is not None:
        conditions.append(ArchiveEntry.check_status == filters.check_status)
    if filters.q:
        pattern = f"%{filters.q}%"
        conditions.append(or_(
            ArchiveEntry.title.ilike(pattern),
            ArchiveEntry.external_id.ilike(pattern),
            ArchiveEntry.url.ilike(pattern),
            ArchiveEntry.creator_label.ilike(pattern),
            ArchiveEntry.group_label.ilike(pattern),
        ))

    time_column = getattr(ArchiveEntry, filters.time_field)
    if filters.unknown_time_only:
        conditions.append(time_column.is_(None))
    elif filters.date_from is not None or filters.date_to is not None:
        # SQLite datetime() normalizes both `Z` and `+00:00` UTC ISO strings before
        # comparing them to Beijing midnight boundaries. Calendar end dates are
        # converted to the next local midnight and remain exclusive.
        utc_column = func.datetime(time_column)
        date_conditions = []
        if filters.date_from is not None:
            date_conditions.append(utc_column >= _utc_day_boundary(filters.date_from))
        if filters.date_to is not None:
            date_conditions.append(
                utc_column < _utc_day_boundary(filters.date_to + timedelta(days=1))
            )
        date_condition = and_(*date_conditions)
        if filters.include_unknown_time:
            conditions.append(or_(date_condition, time_column.is_(None)))
        else:
            conditions.append(date_condition)
    return conditions


def list_entries(
    db: Session,
    *,
    filters: ArchiveFilters | Mapping[str, Any] | None = None,
) -> tuple[list[ArchiveEntry], int]:
    """Return one paginated page and a count from the same filter expression."""
    normalized = _coerce_filters(filters)
    conditions = _filter_conditions(normalized)
    count_stmt = select(func.count()).select_from(ArchiveEntry).where(*conditions)
    total = db.execute(count_stmt).scalar_one()

    time_column = getattr(ArchiveEntry, normalized.time_field)
    stmt = (
        select(ArchiveEntry)
        .where(*conditions)
        .order_by(time_column.desc().nullslast(), ArchiveEntry.id.desc())
        .offset((normalized.page - 1) * normalized.limit)
        .limit(normalized.limit)
    )
    return list(db.execute(stmt).scalars().all()), total


def export_entries(
    db: Session,
    *,
    filters: ArchiveFilters | Mapping[str, Any] | None = None,
) -> list[ArchiveEntry]:
    """Return all rows matching the list predicate; page and limit are ignored."""
    normalized = _coerce_filters(filters)
    conditions = _filter_conditions(normalized)
    time_column = getattr(ArchiveEntry, normalized.time_field)
    stmt = select(ArchiveEntry).where(*conditions).order_by(
        time_column.desc().nullslast(), ArchiveEntry.id.desc()
    )
    return list(db.execute(stmt).scalars().all())


def create_job(
    db: Session,
    *,
    job_type: str,
    root_key: str | None = None,
    relative_directory: str | None = None,
    archive_entry_id: int | None = None,
    status: str = "queued",
    cursor: dict[str, Any] | None = None,
    statistics: dict[str, Any] | None = None,
) -> ArchiveJob:
    if job_type not in _JOB_TYPES:
        raise ValueError(f"Unknown archive job type: {job_type!r}")
    if status not in _JOB_STATUSES:
        raise ValueError(f"Unknown archive job status: {status!r}")
    if root_key is not None:
        _require_root_key(root_key)
    if relative_directory is not None:
        relative_directory = normalize_relative_directory(relative_directory)
    job = ArchiveJob(
        job_type=job_type,
        status=status,
        root_key=root_key,
        relative_directory=relative_directory,
        archive_entry_id=archive_entry_id,
        cursor=cursor or {},
        statistics=statistics or {},
    )
    db.add(job)
    db.flush()
    return job


def get_job(db: Session, job_id: str) -> ArchiveJob | None:
    return db.get(ArchiveJob, job_id)


def update_job(db: Session, job: ArchiveJob | str, **fields: Any) -> ArchiveJob:
    if isinstance(job, str):
        job = get_job(db, job)
        if job is None:
            raise LookupError("archive job not found")
    unknown = set(fields) - _EDITABLE_JOB_FIELDS
    if unknown:
        raise ValueError(f"Unsupported archive job fields: {', '.join(sorted(unknown))}")
    if "status" in fields and fields["status"] not in _JOB_STATUSES:
        raise ValueError(f"Unknown archive job status: {fields['status']!r}")
    if "cursor" in fields and not isinstance(fields["cursor"], dict):
        raise ValueError("job cursor must be a JSON object")
    if "statistics" in fields and not isinstance(fields["statistics"], dict):
        raise ValueError("job statistics must be a JSON object")
    for key, value in fields.items():
        setattr(job, key, value)
    job.updated_at = now_iso()
    if job.status in {"completed", "partial", "failed"}:
        job.lease_owner = None
        job.lease_expires_at = None
    db.flush()
    return job


def claim_next_job(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> ArchiveJob | None:
    """Atomically lease the oldest queued job or a running job with an expired lease."""
    if not worker_id or len(worker_id) > 100:
        raise ValueError("worker_id must contain 1 to 100 characters")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    now_text = current.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_text = (current + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    eligible = or_(
        ArchiveJob.status == "queued",
        and_(
            ArchiveJob.status == "running",
            or_(ArchiveJob.lease_expires_at.is_(None), ArchiveJob.lease_expires_at <= now_text),
        ),
    )
    candidate_id = (
        select(ArchiveJob.id)
        .where(eligible)
        .order_by(ArchiveJob.created_at, ArchiveJob.id)
        .limit(1)
        .scalar_subquery()
    )
    claim = (
        update(ArchiveJob)
        .where(ArchiveJob.id == candidate_id, eligible)
        .values(
            status="running",
            lease_owner=worker_id,
            lease_expires_at=expires_text,
            lease_attempts=ArchiveJob.lease_attempts + 1,
            started_at=func.coalesce(ArchiveJob.started_at, now_text),
            updated_at=now_text,
        )
        .returning(ArchiveJob.id)
        .execution_options(synchronize_session=False)
    )
    claimed_id = db.execute(claim).scalar_one_or_none()
    if claimed_id is None:
        return None
    db.flush()
    return db.get(ArchiveJob, claimed_id, populate_existing=True)


def create_revision(
    db: Session,
    *,
    archive_entry_id: int,
    before_values: dict[str, Any],
    after_values: dict[str, Any],
    source: str = "manual",
) -> ArchiveRevision:
    if not source or len(source) > 40:
        raise ValueError("revision source must contain 1 to 40 characters")
    revision = ArchiveRevision(
        archive_entry_id=archive_entry_id,
        before_values=before_values,
        after_values=after_values,
        source=source,
    )
    db.add(revision)
    db.flush()
    return revision


def list_revisions(db: Session, archive_entry_id: int) -> list[ArchiveRevision]:
    stmt = (
        select(ArchiveRevision)
        .where(ArchiveRevision.archive_entry_id == archive_entry_id)
        .order_by(ArchiveRevision.changed_at.desc(), ArchiveRevision.id.desc())
    )
    return list(db.execute(stmt).scalars().all())
