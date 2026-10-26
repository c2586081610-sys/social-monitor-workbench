"""Durable pipeline download receipts and legacy media registration.

The caller owns the Work/ArchiveEntry transaction. Persist the returned entry
and its sync job with ``db.commit()`` before calling the dedicated-session
``sync_archive_entry`` service or starting transcription.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ArchiveEntry, ArchiveJob, Work
from app.repositories import archive_repo, task_repo
from app.services.archive_metadata_service import build_archive_metadata
from app.utils.archive_paths import (
    make_archive_parent_relative,
    make_work_directory_name,
    normalize_archive_relative_path,
    relative_path_from_root,
    resolve_archive_path,
)


_MEDIA_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".aiff", ".alac", ".avi", ".avif", ".bmp", ".f4v", ".flac", ".flv",
    ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".m4a", ".m4v", ".mkv", ".mov", ".mp3",
    ".mp4", ".m2ts", ".m2v", ".mjpeg", ".mpeg", ".mpg", ".oga", ".ogv", ".ogg", ".opus",
    ".png", ".qt", ".rm", ".rmvb", ".ts", ".tif", ".tiff", ".wav", ".webm", ".webp", ".wma", ".wmv",
}
_DERIVED_DIRS = {
    "frames", "frame", "transcript", "transcripts", "notes", "note", "comment_images",
    "comment-images", "笔记", "转写", "关键帧", "抽帧",
}
_IMAGE_EXTENSIONS = {".avif", ".gif", ".jpg", ".jpeg", ".png", ".webp"}


class ArchiveCheckpointConflict(RuntimeError):
    """A physical archive path is already associated with another identity."""

    def __init__(self, archive_entry_id: int, message: str = "archive path identity conflict") -> None:
        self.archive_entry_id = archive_entry_id
        super().__init__(message)


@dataclass(frozen=True)
class LegacyRegistration:
    archive_entry_id: int
    files: tuple[dict[str, Any], ...]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _path_key(value: str) -> str:
    return os.path.normcase(value.replace("\\", "/"))


def _inside_directory(relative_path: str, relative_directory: str) -> bool:
    prefix = relative_directory.rstrip("/") + "/"
    return _path_key(relative_path).startswith(_path_key(prefix))


def _is_original_media(relative_path: str, relative_directory: str) -> bool:
    if not _inside_directory(relative_path, relative_directory):
        return False
    local = relative_path[len(relative_directory.rstrip("/")) + 1:].replace("\\", "/")
    parts = [part.casefold() for part in local.split("/")]
    if any(part in _DERIVED_DIRS for part in parts[:-1]):
        return False
    if len(parts) == 1 and parts[0] in {"cover.jpg", "cover.png"}:
        return False
    if parts[-1] in {
        "frame_manifest.json", "transcript.json", "transcript.txt", "transcript.srt",
        "作品信息.csv", "作品信息.json", "作品信息.md",
    }:
        return False
    return Path(parts[-1]).suffix.casefold() in _MEDIA_EXTENSIONS


def _entry_metadata_seed(work: Work, entry: ArchiveEntry | None) -> dict[str, Any]:
    """Seed the network resolver from persisted Work and trusted Entry evidence."""
    metadata = _mapping(getattr(entry, "metadata_json", None)) if entry is not None else {}
    seed = dict(metadata)
    resolver = metadata.get("resolver")
    if isinstance(resolver, Mapping):
        seed.update(resolver)

    if entry is not None and entry.published_at:
        provenance = _mapping(metadata.get("provenance"))
        publication = _mapping(provenance.get("published_at"))
        seed.update({
            "published_at": entry.published_at,
            "published_time_source": entry.published_time_source,
            "published_time_precision": entry.published_time_precision,
            "published_time_timezone": publication.get("source_timezone") or publication.get("timezone"),
            "published_time_verified": bool(
                entry.check_status == "verified"
                and entry.published_time_source
                and entry.published_time_precision
            ),
            "metadata_checked_at": entry.metadata_checked_at,
        })
    if entry is not None:
        if not seed.get("title"):
            seed["title"] = entry.title
        if not seed.get("metadata_checked_at") and entry.metadata_checked_at:
            seed["metadata_checked_at"] = entry.metadata_checked_at

    work_has_provenance = bool(
        getattr(work, "published_at", None)
        and getattr(work, "published_time_source", None)
        and getattr(work, "published_time_precision", None)
    )
    entry_has_verified_publication = bool(
        entry is not None
        and entry.published_at
        and entry.published_time_source
        and entry.published_time_precision
        and entry.check_status == "verified"
    )
    work_checked = getattr(work, "metadata_checked_at", None)
    entry_checked = getattr(entry, "metadata_checked_at", None) if entry is not None else None
    work_is_newer = bool(work_checked and (not entry_checked or str(work_checked) > str(entry_checked)))
    if work_has_provenance and (not entry_has_verified_publication or work_is_newer):
        seed.update({
            "published_at": work.published_at,
            "published_time_source": getattr(work, "published_time_source", None),
            "published_time_precision": getattr(work, "published_time_precision", None),
            "published_time_timezone": getattr(work, "published_time_timezone", None),
            "published_time_verified": bool(
                getattr(work, "published_time_source", None)
                and getattr(work, "published_time_precision", None)
            ),
            "metadata_checked_at": work_checked,
        })
    if not seed.get("metadata_checked_at"):
        seed["metadata_checked_at"] = getattr(work, "metadata_checked_at", None)
    if not seed.get("title"):
        seed["title"] = work.title
    return seed


def archive_metadata_seed(work: Work, entry: ArchiveEntry | None = None) -> dict[str, Any]:
    """Public resolver seed preserving Entry columns and source-local timezone."""
    return _entry_metadata_seed(work, entry)


def publication_provenance_from_work(work: Work) -> dict[str, Any] | None:
    source = getattr(work, "published_time_source", None)
    precision = getattr(work, "published_time_precision", None)
    value = getattr(work, "published_at", None)
    if not source or precision not in {"day", "minute", "second"} or not value:
        return None
    source_timezone = getattr(work, "published_time_timezone", None) or "UTC"
    return {
        "value": value,
        "source": source,
        "precision": precision,
        "timezone": source_timezone,
        "source_timezone": source_timezone,
        "verified": True,
        "check_status": "verified",
        "checked_at": getattr(work, "metadata_checked_at", None),
    }


def resolve_work_directory(
    work: Work,
    *,
    root_key: str = "media",
    publication_provenance: Mapping[str, Any] | None = None,
    existing_entry: ArchiveEntry | None = None,
) -> tuple[str, Path]:
    """Return the exact stored physical directory or a new stable root-relative one."""
    if root_key not in settings.archive_root_paths:
        raise ValueError("unknown archive root")

    stored = getattr(work, "media_path", None)
    if stored:
        relative = relative_path_from_root(root_key, str(stored))
        return relative, resolve_archive_path(root_key, relative)

    if existing_entry is not None and existing_entry.root_key == root_key:
        relative = normalize_archive_relative_path(existing_entry.relative_directory)
        work.media_path = relative
        return relative, resolve_archive_path(root_key, relative)

    parent = make_archive_parent_relative(work)
    name = make_work_directory_name(
        work,
        root_key,
        parent,
        publication_provenance=dict(publication_provenance or {}),
    )
    relative = normalize_archive_relative_path(f"{parent}/{name}")
    return relative, resolve_archive_path(root_key, relative)


def _entry_for_work_path(db: Session, work: Work, root_key: str, relative_directory: str) -> ArchiveEntry | None:
    entry = archive_repo.get_entry_by_path(db, root_key, relative_directory)
    if entry is not None:
        return entry
    matches = [
        item for item in archive_repo.list_by_work(db, work.id)
        if item.root_key == root_key
        and _path_key(normalize_archive_relative_path(item.relative_directory))
        == _path_key(relative_directory)
    ]
    return matches[0] if matches else None


def _record_entry_conflict(
    db: Session,
    entry: ArchiveEntry,
    field: str,
    retained: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> None:
    metadata = _mapping(entry.metadata_json)
    evidence = list(metadata.get("conflict_evidence") or [])
    item = {
        "field": field,
        "retained": dict(retained),
        "incoming": dict(incoming),
    }
    if item not in evidence:
        evidence.append(item)
    metadata["conflict_evidence"] = evidence
    conflicts = list(metadata.get("conflicts") or [])
    if field not in conflicts:
        conflicts.append(field)
    metadata["conflicts"] = conflicts
    entry.metadata_json = metadata
    entry.check_status = "conflict"
    entry.sync_status = "pending"
    entry.sync_error = None
    ensure_archive_sync_job(db, entry)
    db.flush()


def _record_identity_conflict(db: Session, entry: ArchiveEntry, work: Work) -> None:
    _record_entry_conflict(
        db,
        entry,
        "archive_identity",
        {"work_id": entry.work_id, "platform": entry.platform, "external_id": entry.external_id},
        {"work_id": work.id, "platform": work.platform, "external_id": work.external_id},
    )


def _assert_entry_identity(db: Session, entry: ArchiveEntry | None, work: Work) -> None:
    if entry is None:
        return
    mismatch = (
        (entry.work_id is not None and entry.work_id != work.id)
        or entry.platform != work.platform
        or (entry.external_id not in (None, "") and str(entry.external_id) != str(work.external_id))
    )
    if mismatch:
        _record_identity_conflict(db, entry, work)
        raise ArchiveCheckpointConflict(entry.id)


def assert_work_archive_identity(db: Session, entry: ArchiveEntry | None, work: Work) -> None:
    """Public pre-download guard for an already registered physical directory."""
    _assert_entry_identity(db, entry, work)


def ensure_archive_sync_job(db: Session, entry: ArchiveEntry) -> ArchiveJob | None:
    """Persist one recoverable sync intent alongside the pending entry update."""
    from app.utils.archive_fingerprint import entry_content_fingerprint

    fingerprint = entry_content_fingerprint(entry)
    active = db.execute(
        select(ArchiveJob).where(
            ArchiveJob.job_type == "sync",
            ArchiveJob.archive_entry_id == entry.id,
            ArchiveJob.status.in_(("queued", "running")),
        ).order_by(ArchiveJob.created_at, ArchiveJob.id)
    ).scalars().first()
    if active is not None:
        if active.status == "queued":
            active.cursor = {**_mapping(active.cursor), "entry_fingerprint": fingerprint}
            active.root_key = entry.root_key
            active.relative_directory = entry.relative_directory
            db.flush()
        return active

    # Imported lazily to keep the checkpoint service independent of Task 4's
    # worker module. The utility fingerprints canonical Entry content only.
    return archive_repo.create_job(
        db,
        job_type="sync",
        root_key=entry.root_key,
        relative_directory=entry.relative_directory,
        archive_entry_id=entry.id,
        cursor={"entry_fingerprint": entry_content_fingerprint(entry)},
        statistics={},
    )


def _as_file_record(file: Any, root_key: str, relative_directory: str) -> dict[str, Any]:
    raw_path = getattr(file, "path", None)
    if raw_path is None and isinstance(file, Mapping):
        raw_path = file.get("path", file.get("relative_path"))
    if raw_path is None:
        raise ValueError("download receipt has no media path")
    path_text = os.fspath(raw_path)
    if not Path(path_text).is_absolute():
        path_text = str(resolve_archive_path(root_key, f"{relative_directory}/{path_text}"))
    relative = relative_path_from_root(root_key, path_text)
    if not _inside_directory(relative, relative_directory):
        raise ValueError("download receipt leaves its work directory")
    checked_path = resolve_archive_path(root_key, relative, must_exist=True)
    if not checked_path.is_file():
        raise ValueError("download receipt is not a regular file")
    size = checked_path.stat().st_size
    expected_size = getattr(file, "size_bytes", None)
    if expected_size is None and isinstance(file, Mapping):
        expected_size = file.get("size_bytes")
    if isinstance(expected_size, bool) or size <= 0 or (expected_size is not None and int(expected_size) != size):
        raise ValueError("download receipt size is invalid or stale")
    if not _is_original_media(relative, relative_directory):
        raise ValueError("download receipt is not an original media file")
    expected_hash = getattr(file, "sha256", None)
    if expected_hash is None and isinstance(file, Mapping):
        expected_hash = file.get("sha256")
    if expected_hash:
        digest = hashlib.sha256()
        with checked_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().casefold() != str(expected_hash).casefold():
            raise ValueError("download receipt hash no longer matches the file")
    media_type = getattr(file, "media_type", None)
    if media_type is None and isinstance(file, Mapping):
        media_type = file.get("media_type")
    return {
        "path": str(checked_path),
        "relative_path": relative,
        "size_bytes": size,
        "media_type": media_type,
        "sha256": expected_hash,
        "name": checked_path.name,
    }


def _entry_files_as_receipts(entry: ArchiveEntry, root_key: str, relative_directory: str) -> tuple[dict[str, Any], ...]:
    result = []
    for item in entry.files_json or []:
        if not isinstance(item, Mapping):
            raise ValueError("archive entry contains an invalid file registration")
        raw_relative = item.get("relative_path")
        if not isinstance(raw_relative, str):
            raise ValueError("archive entry contains a file without a relative path")
        relative = normalize_archive_relative_path(raw_relative)
        if not _is_original_media(relative, relative_directory):
            raise ValueError("registered media is not an original file under its work directory")
        path = resolve_archive_path(root_key, relative, must_exist=True)
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError("registered media is empty or unavailable")
        if isinstance(item.get("size_bytes"), bool) or (
            item.get("size_bytes") is not None and int(item["size_bytes"]) != path.stat().st_size
        ):
            raise ValueError("registered media size is stale")
        result.append({
            "path": str(path),
            "relative_path": relative,
            "size_bytes": path.stat().st_size,
            "media_type": item.get("media_type"),
            "sha256": item.get("sha256"),
            "name": item.get("name") or path.name,
        })
    return tuple(result)


def _media_urls(work: Work) -> list[str]:
    value = getattr(work, "media_urls", None)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _image_signature(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            data = stream.read(32)
    except OSError:
        return False
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith((b"GIF87a", b"GIF89a"))
        or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        or (len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"})
    )


def _legacy_image_records(work: Work, root_key: str, relative_directory: str) -> list[dict[str, Any]]:
    if work.platform != "twitter":
        raise ValueError("legacy image media has no supported source adapter")
    urls = _media_urls(work)
    if not urls:
        raise ValueError("legacy image work has no expected source album")
    for url in urls:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not (host == "twimg.com" or host.endswith(".twimg.com")):
            raise ValueError("legacy image source is unsupported")

    image_dir = resolve_archive_path(root_key, f"{relative_directory}/images", must_exist=True)
    manifest_path = image_dir / "frame_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("legacy image album manifest is unavailable") from exc
    frames = manifest.get("frames") if isinstance(manifest, dict) else None
    if not isinstance(frames, list) or len(frames) != len(urls):
        raise ValueError("legacy image album is incomplete")
    if [item.get("source_url") for item in frames if isinstance(item, Mapping)] != urls:
        raise ValueError("legacy image album identity does not match its source list")

    records = []
    for frame in frames:
        name = frame.get("file") if isinstance(frame, Mapping) else None
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("legacy image album contains an invalid file reference")
        relative = normalize_archive_relative_path(f"{relative_directory}/images/{name}")
        path = resolve_archive_path(root_key, relative, must_exist=True)
        if path.suffix.casefold() not in _IMAGE_EXTENSIONS or path.stat().st_size <= 0 or not _image_signature(path):
            raise ValueError("legacy image album contains invalid media")
        records.append({"path": str(path), "size_bytes": path.stat().st_size, "media_type": "image"})
    return records


def _legacy_media_records(work: Work, root_key: str, relative_directory: str) -> list[dict[str, Any]]:
    content_type = str(getattr(work, "content_type", "video") or "video").lower()
    if content_type == "text":
        return []
    if content_type == "image":
        return _legacy_image_records(work, root_key, relative_directory)

    root = resolve_archive_path(root_key, relative_directory, must_exist=True)
    if not root.is_dir():
        raise ValueError("legacy work media path is not a directory")
    records: list[dict[str, Any]] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept = []
        for name in dirs:
            child = current_path / name
            if name.casefold() in _DERIVED_DIRS:
                continue
            relative = child.relative_to(resolve_archive_path(root_key, "", allow_root=True)).as_posix()
            try:
                checked = resolve_archive_path(root_key, relative, must_exist=True)
            except (OSError, ValueError):
                continue
            if checked.is_dir():
                kept.append(name)
        dirs[:] = kept
        for name in names:
            if Path(name).suffix.casefold() not in _MEDIA_EXTENSIONS:
                continue
            candidate = current_path / name
            relative = candidate.relative_to(resolve_archive_path(root_key, "", allow_root=True)).as_posix()
            try:
                checked = resolve_archive_path(root_key, relative, must_exist=True)
            except (OSError, ValueError):
                continue
            if _is_original_media(relative, relative_directory) and checked.is_file() and checked.stat().st_size > 0:
                records.append({"path": str(checked), "size_bytes": checked.stat().st_size})
    return records


def register_legacy_media(
    db: Session,
    work: Work,
    *,
    root_key: str = "media",
    publication_provenance: Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
) -> LegacyRegistration | None:
    """Durably register old files only when media_path and succeeded Task agree.

    This function does not commit. It never creates a historical download time;
    callers commit its Entry and sync-job intent before they reuse the returned
    registration with a downloader adapter.
    """
    task = task_repo.get_by_work_stage(db, work.id, "download")
    if not getattr(work, "media_path", None) or task is None or task.status != "succeeded":
        return None
    relative_directory = relative_path_from_root(root_key, str(work.media_path))
    existing = _entry_for_work_path(db, work, root_key, relative_directory)
    _assert_entry_identity(db, existing, work)

    if existing is not None and existing.files_json:
        files = _entry_files_as_receipts(existing, root_key, relative_directory)
        if existing.sync_status != "ready":
            ensure_archive_sync_job(db, existing)
            db.flush()
        return LegacyRegistration(existing.id, files)
    else:
        files = tuple(_legacy_media_records(work, root_key, relative_directory))
    if not files and str(work.content_type or "video").lower() != "text":
        return None

    metadata = build_archive_metadata(
        work,
        root_key,
        relative_directory,
        downloaded_files=list(files),
        existing=existing,
        publication_provenance=publication_provenance,
        download_provenance={"disposition": "reused"},
        source_context=source_context,
    )
    if existing is not None and not existing.files_json and not files:
        metadata["check_status"] = existing.check_status
    entry = archive_repo.upsert_entry(
        db,
        root_key=root_key,
        relative_directory=relative_directory,
        **metadata,
    )
    ensure_archive_sync_job(db, entry)
    db.flush()
    return LegacyRegistration(entry.id, tuple(_entry_files_as_receipts(entry, root_key, relative_directory)))


def record_download_checkpoint(
    db: Session,
    work: Work,
    result: Any,
    *,
    root_key: str = "media",
    download_source: str | None = None,
    publication_provenance: Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
) -> int:
    """Upsert verified media and a pending sidecar sync in the caller's transaction.

    Only a new ``downloaded`` receipt updates Work.downloaded_at/source. Reuse
    and pure-text dispositions preserve the prior receipt values.
    """
    disposition = getattr(result, "disposition", None)
    receipt_files = tuple(getattr(result, "files", ()) or ())
    if disposition not in {"downloaded", "reused", "not_required"}:
        raise ValueError("unsupported download receipt disposition")
    if disposition == "not_required":
        if receipt_files or getattr(result, "completed_at", None) is not None:
            raise ValueError("text-only receipt must not contain media or a completion time")
        if str(work.content_type or "").lower() != "text":
            raise ValueError("only text works can skip original media download")
    elif not receipt_files:
        raise ValueError("media receipts require every original media file")
    elif str(work.content_type or "").lower() == "image":
        expected_urls = _media_urls(work)
        if work.platform != "twitter" or not expected_urls or len(receipt_files) != len(expected_urls):
            raise ValueError("image receipt does not cover the complete supported album")

    completed_at = getattr(result, "completed_at", None)
    download_provenance: dict[str, Any] = {"disposition": disposition}
    if disposition == "downloaded":
        if not download_source or not isinstance(completed_at, str):
            raise ValueError("new download receipt requires its source and completion time")
        try:
            parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("download receipt time is invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("download receipt time must include a timezone")
        download_provenance.update({
            "value": parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": download_source,
            "timezone": "UTC",
            "precision": "second",
            "verified": True,
        })

    entries = archive_repo.list_by_work(db, work.id)
    existing_directory_entry = next(
        (item for item in entries if item.root_key == root_key and work.media_path and
         _path_key(normalize_archive_relative_path(item.relative_directory)) ==
         _path_key(relative_path_from_root(root_key, str(work.media_path)))),
        None,
    )
    directory, _media_dir = resolve_work_directory(
        work,
        root_key=root_key,
        publication_provenance=publication_provenance,
        existing_entry=existing_directory_entry,
    )
    existing = _entry_for_work_path(db, work, root_key, directory)
    _assert_entry_identity(db, existing, work)
    if disposition == "reused" and existing is None:
        raise ValueError("reused media requires an existing ArchiveEntry registration")
    if disposition == "not_required" and existing is not None and existing.files_json:
        _record_entry_conflict(
            db,
            existing,
            "content_type",
            {"content_type": "media", "file_count": len(existing.files_json)},
            {"content_type": "text", "file_count": 0},
        )
        raise ArchiveCheckpointConflict(existing.id, "text work conflicts with registered original media")

    normalized_files = [
        _as_file_record(item, root_key, directory)
        for item in receipt_files
    ]
    normalized_paths = {_path_key(item["relative_path"]) for item in normalized_files}
    if len(normalized_paths) != len(normalized_files):
        raise ValueError("download receipt contains duplicate media paths")
    if disposition == "reused" and existing is not None:
        registered = _entry_files_as_receipts(existing, root_key, directory)
        registered_paths = {_path_key(item["relative_path"]) for item in registered}
        receipt_paths = {_path_key(item["relative_path"]) for item in normalized_files}
        if registered_paths != receipt_paths:
            raise ValueError("reused receipt does not match the complete registered media set")

    if not getattr(work, "media_path", None):
        work.media_path = directory
    if disposition == "downloaded":
        work.downloaded_at = download_provenance["value"]
        work.download_time_source = download_source
    fields = build_archive_metadata(
        work,
        root_key,
        directory,
        downloaded_files=normalized_files,
        existing=existing,
        publication_provenance=publication_provenance,
        download_provenance=download_provenance,
        source_context=source_context,
    )

    metadata_json = _mapping(fields.get("metadata_json"))
    resolved = source_context if isinstance(source_context, Mapping) else None
    if resolved:
        previous = metadata_json.get("resolver")
        merged_resolution = dict(previous) if isinstance(previous, Mapping) else {}
        merged_resolution.update({key: value for key, value in resolved.items() if value is not None})
        metadata_json["resolver"] = merged_resolution
    fields["metadata_json"] = metadata_json

    entry = archive_repo.upsert_entry(
        db,
        root_key=root_key,
        relative_directory=directory,
        **fields,
    )
    ensure_archive_sync_job(db, entry)
    db.flush()
    return entry.id
