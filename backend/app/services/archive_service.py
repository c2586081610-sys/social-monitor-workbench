"""Application facade for the authenticated local archive API."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import archive_root_policy, settings
from app.core.errors import conflict, not_found, validation
from app.models import ArchiveEntry, ArchiveJob, Creator, Group, Work
from app.repositories import archive_repo
from app.schemas.archive import (
    ArchiveEntryDetail,
    ArchiveEntrySchema,
    ArchiveFilters,
    ArchiveJobSchema,
    ArchiveMetadataPatch,
    ArchiveRevisionSchema,
)
from app.services.archive_metadata_service import (
    CANONICAL_CSV_HEADERS,
    archive_entry_csv_row,
    archive_entry_payload,
)
from app.services.archive_scan_service import canonical_file_id, safe_metadata_projection
from app.utils.archive_paths import normalize_archive_relative_path, resolve_archive_path
from app.utils.archive_fingerprint import entry_content_fingerprint
from app.utils.timeutil import now_iso


_JOB_ACTIVE = ("queued", "running")
_PLATFORM_HOSTS = {
    "bilibili": {"bilibili.com", "b23.tv"},
    "douyin": {"douyin.com", "iesdouyin.com"},
    "xhs": {"xiaohongshu.com", "xhslink.com"},
    "twitter": {"x.com", "twitter.com", "t.co"},
    "wechat": {"mp.weixin.qq.com", "weixin.qq.com"},
}
_URL_ID_PATTERNS = {
    "bilibili": re.compile(r"(?:^|/)video/(BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,18})(?:/|$)", re.I),
    "douyin": re.compile(r"/(?:video|share/video)/([0-9]{8,30})(?:/|$)"),
    "xhs": re.compile(r"/(?:explore|discovery/item)/([A-Za-z0-9_-]{6,128})(?:/|$)"),
    "twitter": re.compile(r"/(?:i/web/)?status/([0-9]{5,25})(?:/|$)"),
    "wechat": re.compile(r"/(?:s|mp)/([A-Za-z0-9_-]{6,128})(?:/|$)"),
}
_EXTERNAL_ID_PATTERNS = {
    "bilibili": re.compile(r"(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,18})", re.I),
    "douyin": re.compile(r"[0-9]{8,30}"),
    "xhs": re.compile(r"[A-Za-z0-9_-]{6,128}"),
    "twitter": re.compile(r"[0-9]{5,25}"),
    "wechat": re.compile(r"[A-Za-z0-9_.:-]{1,200}"),
}
_TIME_PRECISIONS = {"day", "minute", "second"}
_CLEARABLE_CANONICAL_FIELDS = {
    "external_id",
    "url",
    "creator_id",
    "creator_label",
    "group_id",
    "group_label",
    "published_at",
    "published_time_precision",
}
_MAX_SERVABLE_BYTES = 8 * 1024 * 1024 * 1024


def _entry_or_404(db: Session, archive_id: int) -> ArchiveEntry:
    entry = archive_repo.get_entry(db, archive_id)
    if entry is None:
        raise not_found("ARCHIVE_ENTRY_NOT_FOUND")
    return entry


def entry_payload(entry: ArchiveEntry) -> dict[str, Any]:
    """Serialize an entry using the canonical DTO builder and safe metadata."""
    payload = archive_entry_payload(entry)
    payload["metadata"] = _sanitize_metadata_urls(safe_metadata_projection(payload.get("metadata")))
    payload["url"] = _safe_public_url(payload.get("url"))
    payload["sync_error"] = "ARCHIVE_SYNC_FAILED" if payload.get("sync_error") else None
    return ArchiveEntrySchema.model_validate(payload).model_dump(mode="json")


def job_payload(job: ArchiveJob) -> dict[str, Any]:
    payload = ArchiveJobSchema.model_validate(job).model_dump(mode="json")
    payload["cursor"] = _sanitize_metadata_urls(safe_metadata_projection(payload.get("cursor")))
    payload["statistics"] = _sanitize_metadata_urls(safe_metadata_projection(payload.get("statistics")))
    payload["error"] = "ARCHIVE_JOB_FAILED" if payload.get("error") else None
    return payload


def list_archive_entries(db: Session, filters: ArchiveFilters) -> dict[str, Any]:
    entries, total = archive_repo.list_entries(db, filters=filters)
    items = [entry_payload(item) for item in entries]
    return {
        "items": items,
        "total": total,
        "page": filters.page,
        "limit": filters.limit,
        "has_more": filters.page * filters.limit < total,
    }


def archive_policy() -> dict[str, Any]:
    return archive_root_policy()


def _csv_bytes(entries: list[ArchiveEntry]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CANONICAL_CSV_HEADERS, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for entry in entries:
        row = archive_entry_csv_row(entry)
        row["平台链接"] = _safe_public_url(row.get("平台链接")) or ""
        writer.writerow({key: _protect_csv_formula(value) for key, value in row.items()})
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def export_archive_csv(db: Session, filters: ArchiveFilters) -> bytes:
    entries = archive_repo.export_entries(db, filters=filters)
    return _csv_bytes(entries)


def entry_info_csv(db: Session, archive_id: int) -> bytes:
    entry = _entry_or_404(db, archive_id)
    return _csv_bytes([entry])


def archive_detail(db: Session, archive_id: int) -> dict[str, Any]:
    entry = _entry_or_404(db, archive_id)
    revisions = archive_repo.list_revisions(db, archive_id)
    data = entry_payload(entry)
    data["revisions"] = []
    for revision in revisions:
        values = ArchiveRevisionSchema.model_validate(revision).model_dump(mode="json")
        values["before_values"] = safe_metadata_projection(values["before_values"])
        values["after_values"] = safe_metadata_projection(values["after_values"])
        values["before_values"]["url"] = _safe_public_url(values["before_values"].get("url"))
        values["after_values"]["url"] = _safe_public_url(values["after_values"].get("url"))
        data["revisions"].append(values)
    return ArchiveEntryDetail.model_validate(data).model_dump(mode="json")


def archive_file(db: Session, archive_id: int, file_id: str) -> tuple[Path, str, str]:
    entry = _entry_or_404(db, archive_id)
    for raw in entry.files_json or []:
        if not isinstance(raw, dict):
            continue
        relative = raw.get("relative_path")
        try:
            normalized = normalize_archive_relative_path(relative)
            registered_id = canonical_file_id(entry.root_key, normalized)
        except (TypeError, ValueError):
            continue
        if registered_id != file_id:
            continue
        try:
            file_path = resolve_archive_path(entry.root_key, normalized, must_exist=True)
            if not file_path.is_file():
                break
            size = file_path.stat().st_size
            registered_size = raw.get("size_bytes")
            if size <= 0 or size > _MAX_SERVABLE_BYTES:
                break
            if isinstance(registered_size, bool) or not isinstance(registered_size, int) or registered_size != size:
                break
        except (OSError, ValueError):
            break
        import mimetypes

        guessed_type = mimetypes.guess_type(file_path.name)[0]
        if guessed_type and guessed_type.split("/", 1)[0] not in {"audio", "video", "image"}:
            break
        media_type = guessed_type or "application/octet-stream"
        return file_path, media_type, file_path.name
    raise not_found("ARCHIVE_FILE_NOT_FOUND")


def create_scan_job(db: Session, *, root_key: str, relative_directory: str | None) -> ArchiveJob:
    if root_key not in settings.archive_root_paths:
        raise validation("ARCHIVE_ROOT_INVALID")
    try:
        relative = normalize_archive_relative_path(relative_directory or "", allow_root=True)
        target = resolve_archive_path(root_key, relative, allow_root=True, must_exist=True)
        if not target.is_dir():
            raise ValueError("scan target is not a directory")
    except (OSError, ValueError):
        raise validation("ARCHIVE_SCAN_TARGET_INVALID") from None

    normalized = relative or None
    duplicate = db.execute(
        select(ArchiveJob)
        .where(
            ArchiveJob.job_type == "scan",
            ArchiveJob.root_key == root_key,
            ArchiveJob.relative_directory == normalized,
            ArchiveJob.status.in_(_JOB_ACTIVE),
        )
        .order_by(ArchiveJob.created_at, ArchiveJob.id)
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is not None:
        return duplicate
    job = archive_repo.create_job(
        db,
        job_type="scan",
        root_key=root_key,
        relative_directory=normalized,
        statistics={"indexed": 0, "updated": 0, "conflict": 0, "unknown": 0, "failed": 0},
    )
    db.commit()
    return job


def get_archive_job(db: Session, job_id: str) -> dict[str, Any]:
    job = archive_repo.get_job(db, job_id)
    if job is None:
        raise not_found("ARCHIVE_JOB_NOT_FOUND")
    return job_payload(job)


def create_entry_job(db: Session, archive_id: int, job_type: str) -> ArchiveJob:
    entry = _entry_or_404(db, archive_id)
    if job_type == "refresh":
        metadata = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
        if metadata.get("identity_review_required"):
            raise conflict("ARCHIVE_IDENTITY_REVIEW_REQUIRED")
        if not entry.external_id:
            raise conflict("ARCHIVE_IDENTITY_REQUIRED")
    duplicate = db.execute(
        select(ArchiveJob)
        .where(
            ArchiveJob.job_type == job_type,
            ArchiveJob.archive_entry_id == entry.id,
            ArchiveJob.status.in_(_JOB_ACTIVE),
        )
        .order_by(ArchiveJob.created_at, ArchiveJob.id)
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is not None:
        return duplicate
    if job_type == "sync":
        entry.sync_status = "pending"
        entry.sync_error = None
    job = archive_repo.create_job(
        db,
        job_type=job_type,
        root_key=entry.root_key,
        relative_directory=entry.relative_directory,
        archive_entry_id=entry.id,
        cursor={"content_fingerprint": entry_content_fingerprint(entry)} if job_type == "sync" else {},
        statistics={"attempts": 0},
    )
    db.commit()
    return job


def _validate_identity_url(platform: str, external_id: str | None, url: str | None) -> bool:
    """Validate exact hostname and, when supplied, platform path identity."""
    if external_id is not None:
        valid_id = _EXTERNAL_ID_PATTERNS.get(platform)
        if valid_id is None or not valid_id.fullmatch(external_id):
            raise validation("ARCHIVE_EXTERNAL_ID_INVALID")
    if url is None:
        return external_id is not None
    try:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.port not in (None, 80, 443):
            raise ValueError
    except ValueError:
        raise validation("ARCHIVE_URL_INVALID") from None
    domains = _PLATFORM_HOSTS.get(platform, set())
    if not any(host == domain or host.endswith("." + domain) for domain in domains):
        raise validation("ARCHIVE_URL_PLATFORM_MISMATCH")
    pattern = _URL_ID_PATTERNS.get(platform)
    match = pattern.search(parsed.path) if pattern else None
    found_id = match.group(1) if match else None
    if external_id is not None:
        if found_id and found_id.casefold() != external_id.casefold():
            raise validation("ARCHIVE_URL_ID_MISMATCH")
        if not found_id:
            raise validation("ARCHIVE_URL_ID_REQUIRED")
    return found_id is not None


def _safe_public_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
            return None
        if not any(host == domain or host.endswith("." + domain) for domains in _PLATFORM_HOSTS.values() for domain in domains):
            return None
        # Drop query and fragment values because legacy share links may carry
        # tracking tokens or credentials. The platform/path identity stays intact.
        return parsed._replace(query="", fragment="").geturl()
    except ValueError:
        return None


def _sanitize_metadata_urls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_metadata_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_metadata_urls(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata_urls(item) for item in value]
    if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
        return _safe_public_url(value)
    return value


def _protect_csv_formula(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    probe = value.lstrip(" \t\r\n")
    return "'" + value if probe[:1] in {"=", "+", "-", "@", "\t", "\r"} else value


def _iso_utc(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        raise validation("ARCHIVE_PUBLICATION_TIME_MUST_BE_AWARE")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _manual_revision_values(entry: ArchiveEntry) -> dict[str, Any]:
    return {
        "platform": entry.platform,
        "external_id": entry.external_id,
        "title": entry.title,
        "url": entry.url,
        "creator_id": entry.creator_id,
        "creator_label": entry.creator_label,
        "group_id": entry.group_id,
        "group_label": entry.group_label,
        "published_at": entry.published_at,
        "published_time_source": entry.published_time_source,
        "published_time_precision": entry.published_time_precision,
        "metadata_checked_at": entry.metadata_checked_at,
        "work_id": entry.work_id,
        "check_status": entry.check_status,
    }


def patch_archive_metadata(db: Session, archive_id: int, patch: ArchiveMetadataPatch) -> dict[str, Any]:
    entry = _entry_or_404(db, archive_id)
    values = patch.model_dump(mode="json", exclude_unset=True)
    before = _manual_revision_values(entry)
    merged = {key: getattr(entry, key) for key in (
        "platform", "external_id", "title", "url", "creator_id", "creator_label",
        "group_id", "group_label", "published_at", "published_time_precision",
    )}
    merged.update(values)
    platform = merged["platform"]
    external_id = merged["external_id"]
    if external_id is not None and (not isinstance(external_id, str) or not external_id.strip()):
        raise validation("ARCHIVE_EXTERNAL_ID_INVALID")
    external_id = external_id.strip() if isinstance(external_id, str) else None
    has_identity_url = _validate_identity_url(platform, external_id, merged["url"])
    merged["url"] = _safe_public_url(merged["url"]) if merged["url"] is not None else None

    if "published_at" in values:
        published_at = _iso_utc(values["published_at"])
        precision = merged["published_time_precision"]
        if published_at is not None and precision not in _TIME_PRECISIONS:
            raise validation("ARCHIVE_PUBLICATION_PRECISION_REQUIRED")
        if published_at is None:
            merged["published_time_precision"] = None
    else:
        published_at = entry.published_at
        if "published_time_precision" in values and merged["published_time_precision"] not in _TIME_PRECISIONS and published_at:
            raise validation("ARCHIVE_PUBLICATION_PRECISION_INVALID")

    creator = None
    if merged["creator_id"] is not None:
        creator = db.get(Creator, merged["creator_id"])
        if creator is None:
            raise validation("CREATOR_NOT_FOUND")
        if creator.platform != platform:
            raise validation("ARCHIVE_CREATOR_PLATFORM_MISMATCH")
        merged["creator_label"] = creator.name
    elif "creator_id" in values and "creator_label" not in values:
        merged["creator_label"] = None

    group = None
    if merged["group_id"] is not None:
        group = db.get(Group, merged["group_id"])
        if group is None:
            raise validation("GROUP_NOT_FOUND")
        merged["group_label"] = group.name
    elif "group_id" in values and "group_label" not in values:
        merged["group_label"] = None

    work = None
    if external_id:
        work = db.execute(
            select(Work).where(Work.platform == platform, Work.external_id == external_id)
        ).scalar_one_or_none()

    # Omitted values remain intact; publication null explicitly clears its provenance.
    for field in ("platform", "external_id", "title", "url", "creator_id", "creator_label", "group_id", "group_label"):
        if field in values or field in {"creator_label", "group_label"} and field in merged:
            setattr(entry, field, merged[field])
    if "published_at" in values:
        entry.published_at = published_at
        entry.published_time_source = "manual" if published_at is not None else None
        entry.published_time_precision = merged["published_time_precision"]
    elif "published_time_precision" in values:
        entry.published_time_precision = merged["published_time_precision"]

    entry.work_id = work.id if work is not None else None
    if entry.url is not None:
        entry.url = _safe_public_url(entry.url)
    identity_review_required = bool((entry.metadata_json or {}).get("identity_review_required"))
    explicit_identity_choice = "external_id" in values and external_id is not None
    can_verify = bool(
        external_id
        and has_identity_url
        and entry.title.strip()
        and (not identity_review_required or explicit_identity_choice)
    )
    entry.check_status = "verified" if can_verify else "needs_review"
    entry.metadata_checked_at = now_iso() if entry.check_status == "verified" else entry.metadata_checked_at
    entry.metadata_json = dict(entry.metadata_json or {})
    previous_cleared = entry.metadata_json.get("explicit_cleared_fields")
    if not isinstance(previous_cleared, list):
        previous_cleared = []
    explicit_cleared = {
        field
        for field in previous_cleared
        if isinstance(field, str) and field in _CLEARABLE_CANONICAL_FIELDS
    }
    for field, value in values.items():
        if field not in _CLEARABLE_CANONICAL_FIELDS:
            continue
        if value is None:
            explicit_cleared.add(field)
        else:
            explicit_cleared.discard(field)
    # Clearing/reselecting an ID also clears/rebuilds its display label.
    if "creator_id" in values:
        if merged["creator_id"] is None and values.get("creator_label") is None:
            explicit_cleared.add("creator_label")
        else:
            explicit_cleared.discard("creator_label")
    if "group_id" in values:
        if merged["group_id"] is None and values.get("group_label") is None:
            explicit_cleared.add("group_label")
        else:
            explicit_cleared.discard("group_label")
    if explicit_cleared:
        entry.metadata_json["explicit_cleared_fields"] = sorted(explicit_cleared)
    else:
        entry.metadata_json.pop("explicit_cleared_fields", None)
    if explicit_identity_choice and entry.check_status == "verified":
        entry.metadata_json.pop("identity_review_required", None)
        entry.metadata_json.pop("identity_review_reason", None)
        entry.metadata_json.pop("title_candidates", None)
    if "published_at" in values or "published_time_precision" in values:
        provenance = entry.metadata_json.setdefault("provenance", {})
        if isinstance(provenance, dict):
            prior_publication = provenance.get("published_at")
            publication_provenance = dict(prior_publication) if isinstance(prior_publication, dict) else {}
            publication_provenance.update({
                "source": entry.published_time_source,
                "source_timezone": (
                    "UTC" if "published_at" in values
                    else publication_provenance.get("source_timezone") or "UTC"
                ),
                "precision": entry.published_time_precision,
                "verified": bool(entry.published_at and entry.check_status == "verified"),
                "checked_at": entry.metadata_checked_at,
            })
            provenance["published_at"] = publication_provenance
    entry.metadata_json["manual_review"] = {
        "source": "manual",
        "checked_at": entry.metadata_checked_at,
        "check_status": entry.check_status,
        "platform": entry.platform,
        "external_id": entry.external_id,
        "url": _safe_public_url(entry.url),
    }
    entry.sync_status = "pending"
    entry.sync_error = None
    db.flush()
    after = _manual_revision_values(entry)
    archive_repo.create_revision(
        db,
        archive_entry_id=entry.id,
        before_values=before,
        after_values=after,
        source="manual",
    )
    active_sync = db.execute(
        select(ArchiveJob.id).where(
            ArchiveJob.job_type == "sync",
            ArchiveJob.archive_entry_id == entry.id,
            ArchiveJob.status.in_(_JOB_ACTIVE),
        ).limit(1)
    ).scalar_one_or_none()
    if active_sync is None:
        archive_repo.create_job(
            db,
            job_type="sync",
            root_key=entry.root_key,
            relative_directory=entry.relative_directory,
            archive_entry_id=entry.id,
            cursor={"content_fingerprint": entry_content_fingerprint(entry)},
            statistics={"attempts": 0},
        )
    db.commit()
    db.refresh(entry)
    return entry_payload(entry)


def build_archive_filters(
    *,
    platform: str | None = None,
    creator_id: int | None = None,
    group_id: int | None = None,
    work_id: list[int] | None = None,
    root_key: str | None = None,
    q: str | None = None,
    check_status: str | None = None,
    time_field: str = "published_at",
    date_from: date | None = None,
    date_to: date | None = None,
    include_unknown_time: bool = False,
    unknown_time_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> ArchiveFilters:
    if root_key is not None and root_key not in settings.archive_root_paths:
        raise validation("ARCHIVE_ROOT_INVALID")
    try:
        return ArchiveFilters.model_validate(locals())
    except ValidationError as exc:
        # Never include input values (which can contain local paths) in API errors.
        raise validation("ARCHIVE_FILTERS_INVALID") from exc
