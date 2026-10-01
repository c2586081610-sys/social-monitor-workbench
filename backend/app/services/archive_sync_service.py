"""Recoverable atomic sidecar, creator collection, and root catalog sync."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from typing import Any, Iterator

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import ARCHIVE_CATALOG_FILE, ARCHIVE_COLLECTION_FILE, ARCHIVE_INFORMATION_FILES, ARCHIVE_PLATFORM_LABELS
from app.models import ArchiveEntry
from app.repositories.archive_repo import export_entries
from app.services.archive_metadata_service import (
    CANONICAL_CSV_HEADERS,
    CANONICAL_HEADER_ALIASES,
    LEGACY_COLUMN_ALIASES,
    archive_entry_csv_row,
    archive_entry_payload,
    markdown_escape,
    public_archive_metadata,
    split_legacy_columns,
)
from app.utils.archive_paths import normalize_archive_relative_path, relative_path_from_root, resolve_archive_path
from app.utils.timeutil import now_iso


class ArchiveSyncError(RuntimeError):
    """A sync failed; the DB row has a sanitized recoverable error status."""


_PRIVATE_PATH_HEADERS = {"本地媒体路径", "本地路径", "media_path", "local_path", "path", "file_path", "filepath"}
_PLATFORM_LABEL_TO_CODE = {label: code for code, label in ARCHIVE_PLATFORM_LABELS.items()}
_PLATFORM_LABEL_TO_CODE.update({
    "Twitter/X": "twitter",
    "推特": "twitter",
    "B站": "bilibili",
    "哔哩哔哩（B站）": "bilibili",
})
_COLLECTION_MARKER = "合集清单.csv.archive.json"
_MANAGED_MARKER = {"schema_version": 1, "managed_by": "unified-media-archive", "managed": True}
_DERIVED_MEDIA_DIRS = {
    "frames", "frame", "transcript", "transcripts", "notes", "note",
    "comment_images", "comment-images", "笔记", "转写", "关键帧", "抽帧",
}
_CONTENT_FIELDS = (
    "root_key", "relative_directory", "work_id", "platform", "external_id", "title", "url",
    "creator_id", "creator_label", "group_id", "group_label", "published_at",
    "published_time_source", "published_time_precision", "downloaded_at", "download_time_source",
    "download_time_precision", "metadata_checked_at", "check_status", "metadata_version",
    "metadata_json", "files_json",
)


def _session_factory(session_factory: Callable[[], Session] | None) -> Callable[[], Session]:
    if session_factory is not None:
        return session_factory
    from app.core.db import SessionLocal

    return SessionLocal


def _snapshot(entry: ArchiveEntry) -> dict[str, Any]:
    return {name: getattr(entry, name) for name in (*_CONTENT_FIELDS, "id", "sync_status", "sync_error", "synced_at", "created_at", "updated_at")}


def _content_fingerprint(value: Mapping[str, Any]) -> str:
    canonical = {key: value.get(key) for key in _CONTENT_FIELDS}
    packed = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _begin_immediate(db: Session) -> None:
    """Take a brief SQLite write reservation for the final state comparison."""
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


@contextmanager
def _root_lock(root_key: str) -> Iterator[None]:
    root = resolve_archive_path(root_key, "", allow_root=True, must_exist=True)
    if not root.is_dir():
        raise ValueError("Configured archive root is unavailable")
    lock_relative = ".archive-sync.lock"
    lock_path = resolve_archive_path(root_key, lock_relative)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolve_archive_path(root_key, lock_relative)
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            acquired = False
            try:
                while not acquired:
                    lock_file.seek(0)
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        acquired = True
                    except OSError:
                        time.sleep(0.1)
                yield
            finally:
                if acquired:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _safe_error(exc: BaseException) -> str:
    # Exception messages from paths, database drivers and OS APIs can expose
    # machine-local directories or credentials; persist only a stable class.
    return f"Archive synchronization failed ({type(exc).__name__}). Retry after fixing the local storage issue."


def _protect_formula(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    probe = value.lstrip(" \t\r\n")
    if probe[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + value
    return value


def _csv_bytes(headers: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(headers),
        extrasaction="ignore",
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({header: _protect_formula(row.get(header, "")) for header in headers})
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def _parse_csv_bytes(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Historical Chinese spreadsheets may be GB18030; refreshed output is
        # still standardized as UTF-8 with BOM.
        text = content.decode("gb18030")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = list(reader.fieldnames or [])
    if not headers:
        if text.strip():
            raise ValueError("CSV header is missing")
        return [], []
    rows = [{key: value or "" for key, value in row.items() if key is not None} for row in reader]
    return headers, rows


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    return _parse_csv_bytes(path.read_bytes())


def _platform_code(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text in _PLATFORM_LABEL_TO_CODE:
        return _PLATFORM_LABEL_TO_CODE[text]
    known = {"douyin", "bilibili", "xhs", "twitter", "wechat"}
    if text.casefold() in known:
        return text.casefold()
    return None


def _row_value(row: Mapping[str, Any], field: str) -> Any:
    for name in LEGACY_COLUMN_ALIASES.get(field, ()):
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _entry_files(entry: Any) -> list[dict[str, Any]]:
    files = getattr(entry, "files_json", None)
    if files is None and isinstance(entry, Mapping):
        files = entry.get("files_json", entry.get("files", []))
    return [dict(item) for item in (files or []) if isinstance(item, Mapping)]


def _path_references(row: Mapping[str, Any], root_key: str) -> set[str]:
    raw_values: list[str] = []
    for name in (*LEGACY_COLUMN_ALIASES.get("relative_directory", ()), *LEGACY_COLUMN_ALIASES.get("media_path", ())):
        value = row.get(name)
        if isinstance(value, str) and value.strip():
            raw_values.extend(part.strip() for part in value.splitlines() if part.strip())
    row_root = row.get("本地根目录标识") or row.get("root_key")
    if row_root not in (None, "", root_key):
        return set()
    references: set[str] = set()
    for raw in raw_values:
        candidate = Path(raw)
        if candidate.is_absolute() or PureWindowsPath(raw).drive or raw.startswith(("\\", "/")):
            try:
                references.add(relative_path_from_root(root_key, raw))
            except (ValueError, OSError):
                # An absolute reference outside this root is preserved in the
                # legacy row but cannot be used to associate an archive entry.
                continue
        else:
            try:
                references.add(normalize_archive_relative_path(raw))
            except ValueError:
                continue
    return references


def _match_entry(row: Mapping[str, Any], entries: Sequence[Any], root_key: str) -> Any | None:
    row_id = _row_value(row, "external_id")
    row_platform = _platform_code(_row_value(row, "platform"))
    identity_matches = []
    if row_id not in (None, "") and row_platform:
        identity_matches = [
            entry for entry in entries
            if getattr(entry, "external_id", None) == str(row_id)
            and getattr(entry, "platform", None) == row_platform
        ]
    if len(identity_matches) == 1:
        return identity_matches[0]

    path_refs = _path_references(row, root_key)
    if path_refs:
        path_matches = []
        for entry in entries:
            if getattr(entry, "root_key", None) != root_key:
                continue
            known_paths = {str(getattr(entry, "relative_directory", ""))}
            known_paths.update(str(item.get("relative_path", "")) for item in _entry_files(entry))
            if path_refs & known_paths:
                path_matches.append(entry)
        if len(path_matches) == 1:
            return path_matches[0]
        if len(identity_matches) > 1:
            identity_by_path = [item for item in identity_matches if item in path_matches]
            if len(identity_by_path) == 1:
                return identity_by_path[0]
    return None


def _canonical_for_row(entry: Any, row: Mapping[str, Any], *, per_media: bool, root_key: str) -> dict[str, Any]:
    canonical = archive_entry_csv_row(entry)
    if not per_media:
        return canonical
    path_refs = _path_references(row, root_key)
    matching_file = next((item for item in _entry_files(entry) if item.get("relative_path") in path_refs), None)
    if matching_file:
        canonical["本地媒体文件"] = matching_file["relative_path"]
        canonical["媒体数量"] = 1
        canonical["媒体大小（字节）"] = int(matching_file.get("size_bytes") or 0)
    elif path_refs and getattr(entry, "relative_directory", None) not in path_refs:
        # The row matched by platform ID only. Leave its legacy file reference
        # intact, since no exact per-media path was verified.
        canonical["本地媒体文件"] = ""
        canonical["媒体数量"] = ""
        canonical["媒体大小（字节）"] = ""
    return canonical


def _merge_row(row: Mapping[str, Any], canonical: Mapping[str, Any], headers: Sequence[str]) -> dict[str, Any]:
    merged = dict(row)
    for canonical_header in CANONICAL_CSV_HEADERS:
        value = canonical.get(canonical_header, "")
        # Unknown values must not erase old trustworthy CSV values. Status is
        # always explicit and must follow the current canonical check state.
        if value not in (None, "") or canonical_header == "信息核对状态":
            merged[canonical_header] = value
            for alias in CANONICAL_HEADER_ALIASES.get(canonical_header, ()):
                if alias not in headers or alias in _PRIVATE_PATH_HEADERS:
                    continue
                if value not in (None, "") or canonical_header == "信息核对状态":
                    merged[alias] = value
    return merged


def _row_conflicts_identity(row: Mapping[str, Any], entry: Any) -> bool:
    old_id = _row_value(row, "external_id")
    old_platform = _platform_code(_row_value(row, "platform"))
    if old_id not in (None, "") and getattr(entry, "external_id", None) not in (None, ""):
        if str(old_id) != str(entry.external_id):
            return True
    if old_platform and old_platform != getattr(entry, "platform", None):
        return True
    return False


def _headers_with_canonical(headers: Sequence[str]) -> list[str]:
    return list(dict.fromkeys([*headers, *CANONICAL_CSV_HEADERS]))


def refresh_legacy_csv(
    content: bytes,
    entries: Sequence[Any],
    root_key: str,
    *,
    per_media: bool = False,
) -> bytes:
    """Update only verified rows in a legacy CSV; never append collection members.

    The helper accepts the prior bytes and full entry snapshot, returns a BOM CSV,
    and keeps the original row count/custom columns. A file is safely refreshed
    by callers with a same-directory atomic replace.
    """
    headers, rows = _parse_csv_bytes(content)
    if not headers:
        return _csv_bytes(CANONICAL_CSV_HEADERS, [])
    output: list[dict[str, Any]] = []
    all_headers = _headers_with_canonical(headers)
    for row in rows:
        match = _match_entry(row, entries, root_key)
        if match is None or _row_conflicts_identity(row, match):
            output.append(row)
            continue
        canonical = _canonical_for_row(match, row, per_media=per_media, root_key=root_key)
        output.append(_merge_row(row, canonical, all_headers))
    return _csv_bytes(all_headers, output)


def _atomic_replace(root_key: str, relative_path: str, payload: bytes) -> None:
    relative = normalize_archive_relative_path(relative_path)
    target = resolve_archive_path(root_key, relative)
    parent_relative = relative.rpartition("/")[0]
    parent = resolve_archive_path(root_key, parent_relative, allow_root=True)
    parent.mkdir(parents=True, exist_ok=True)
    target = resolve_archive_path(root_key, relative)
    parent = resolve_archive_path(root_key, parent_relative, allow_root=True)
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Re-check the final path after creation of the same-directory temp file.
        target = resolve_archive_path(root_key, relative)
        os.replace(temporary, target)
        temporary = None
        if os.name != "nt":
            try:
                directory_fd = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _entry_metadata_json(entry: Any, prior_csv_rows: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    payload = archive_entry_payload(entry)
    metadata = dict(payload.get("metadata") or {})
    existing_safe = dict(metadata.get("legacy_columns") or {})
    existing_private = dict(metadata.get("private_legacy_columns") or {})
    for row in prior_csv_rows:
        for key, value in row.items():
            if value in (None, ""):
                continue
            target = existing_private if key in _PRIVATE_PATH_HEADERS else existing_safe
            if key not in target:
                target[key] = value
    safe, private = split_legacy_columns({**existing_private, **existing_safe})
    if safe:
        metadata["legacy_columns"] = safe
    else:
        metadata.pop("legacy_columns", None)
    # Keep absolute/private values on the DB row, but never serialize them into
    # JSON sidecars or API metadata. Existing local CSVs retain their old column.
    metadata.pop("private_legacy_columns", None)
    payload["metadata"] = public_archive_metadata(metadata)
    return {"schema_version": 1, **payload}


def _render_info_json(entry: Any, legacy_rows: Sequence[Mapping[str, Any]]) -> bytes:
    body = _entry_metadata_json(entry, legacy_rows)
    return (json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")


def _scrub_public_csv_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep safe custom columns while removing machine-local paths from new outputs."""
    output = []
    for row in rows:
        clean = dict(row)
        for key, value in list(clean.items()):
            if key in _PRIVATE_PATH_HEADERS:
                safe_media = clean.get("本地媒体文件", "")
                clean[key] = safe_media if isinstance(safe_media, str) and not PureWindowsPath(safe_media).drive and not safe_media.startswith(("/", "\\")) else ""
            elif isinstance(value, str) and (
                PureWindowsPath(value).drive or value.startswith(("\\", "/"))
            ) and not value.startswith(("http://", "https://")):
                clean[key] = ""
        output.append(clean)
    return output


def _render_markdown(entry: Any) -> bytes:
    row = archive_entry_csv_row(entry)
    labels = (
        ("作品标题", "作品标题"), ("平台", "平台"), ("平台代码", "平台代码"),
        ("博主", "博主"), ("分组", "分组"), ("作品ID", "作品ID"),
        ("平台链接", "平台链接"), ("发布时间（北京时间）", "发布时间"),
        ("发布时间精度", "发布时间精度"), ("下载完成时间（北京时间）", "下载完成时间"),
        ("发布时间来源", "发布时间来源"), ("下载时间来源", "下载时间来源"),
        ("信息核对状态", "信息核对状态"), ("信息核对时间（北京时间）", "信息核对时间"),
        ("本地根目录标识", "本地根目录标识"), ("本地作品目录", "本地作品目录"),
        ("媒体数量", "媒体数量"), ("媒体大小（字节）", "媒体大小（字节）"),
    )
    lines = [f"# {markdown_escape(row['作品标题'])}", "", "| 字段 | 值 |", "| --- | --- |"]
    for field, label in labels:
        value = row.get(field, "")
        if field == "发布时间（北京时间）" and not value:
            value = "发布时间待核实"
        elif field == "下载完成时间（北京时间）" and not value:
            value = "下载时间未知"
        elif value in (None, ""):
            value = "未知"
        lines.append(f"| {markdown_escape(label)} | {markdown_escape(value)} |")
    files = _entry_files(entry)
    content_type = (getattr(entry, "metadata_json", {}) or {}).get("content_type")
    if files:
        media_description = "\n".join(f"- `{markdown_escape(item.get('relative_path', ''))}` ({int(item.get('size_bytes') or 0)} bytes)" for item in files)
    elif content_type == "text":
        media_description = "无需媒体下载"
    else:
        media_description = "暂无已登记媒体文件"
    lines.extend(("", "## 本地媒体", "", media_description, ""))
    return "\n".join(lines).encode("utf-8")


def _validate_entry_files(entry: Any) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    root_key = entry.root_key
    work_directory = resolve_archive_path(root_key, entry.relative_directory)
    for raw in _entry_files(entry):
        relative = raw.get("relative_path")
        if not isinstance(relative, str):
            raise ValueError("A registered media item has no root-relative path")
        relative = normalize_archive_relative_path(relative)
        if relative.startswith("/"):
            raise ValueError("A registered media item is absolute")
        media = resolve_archive_path(root_key, relative, must_exist=True)
        if not media.is_file():
            raise ValueError("A registered media item is not a file")
        actual_size = media.stat().st_size
        if actual_size <= 0:
            raise ValueError("A registered original media file is empty")
        raw_size = raw.get("size_bytes")
        if raw_size is not None:
            try:
                if int(raw_size) != actual_size:
                    raise ValueError("A registered media size no longer matches the file")
            except (TypeError, ValueError) as exc:
                raise ValueError("A registered media size is invalid or stale") from exc
        if media.suffix.casefold() not in {
            ".3g2", ".3gp", ".aac", ".aiff", ".alac", ".avi", ".avif", ".bmp", ".f4v", ".flac", ".flv",
            ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".m4a", ".m4v", ".mkv",
            ".mov", ".mp3", ".mp4", ".m2ts", ".m2v", ".mjpeg", ".mpeg", ".mpg", ".oga", ".ogv", ".ogg", ".opus",
            ".png", ".qt", ".rm", ".rmvb", ".ts", ".tif", ".tiff", ".wav",
            ".webm", ".webp", ".wma", ".wmv",
        }:
            raise ValueError("A registered media item is not an original media type")
        try:
            inside_work = media.relative_to(work_directory)
        except ValueError as exc:
            raise ValueError("Registered media must remain inside its work directory") from exc
        if any(part.casefold() in _DERIVED_MEDIA_DIRS for part in inside_work.parts[:-1]):
            raise ValueError("Derived files cannot be registered as original media")
        entry_directory = normalize_archive_relative_path(entry.relative_directory).casefold()
        if relative.casefold() in {f"{entry_directory}/cover.jpg", f"{entry_directory}/cover.png"}:
            raise ValueError("Fixed work cover files cannot be registered as original media")
        stable_id = "f_" + hashlib.sha256(f"{root_key}\0{relative}".encode("utf-8")).hexdigest()[:32]
        canonical.append({
            "file_id": stable_id,
            "relative_path": relative,
            "name": str(raw.get("name") or media.name),
            "size_bytes": actual_size,
            "media_type": raw.get("media_type"),
            "sha256": raw.get("sha256"),
        })
    return canonical


def _entry_relative_file(root_key: str, entry: Any, filename: str) -> str:
    return "/".join(part for part in (entry.relative_directory, filename) if part)


def _single_info_csv(root_key: str, entry: Any, old_path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    old_headers, old_rows = _read_csv(old_path)
    all_headers = _headers_with_canonical(old_headers)
    if old_rows:
        matching = [row for row in old_rows if _match_entry(row, [entry], root_key) is not None]
        source_row = (matching or old_rows)[0]
        if _row_conflicts_identity(source_row, entry):
            raise ValueError("Existing work sidecar identity conflicts with the database record")
    else:
        source_row = {}
    canonical = archive_entry_csv_row(entry)
    merged = _merge_row(source_row, canonical, all_headers)
    # One aggregate row represents this work, regardless of its media count.
    return _csv_bytes(all_headers, _scrub_public_csv_rows([merged])), old_rows


def _entry_directory_parent(entry: Any) -> str:
    directory = str(entry.relative_directory)
    return directory.rpartition("/")[0]


def _is_managed_collection(root_key: str, parent: str, collection_path: Path) -> bool:
    if not collection_path.exists():
        return True
    marker_relative = "/".join(part for part in (parent, _COLLECTION_MARKER) if part)
    marker_path = resolve_archive_path(root_key, marker_relative)
    if not marker_path.exists():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return marker == _MANAGED_MARKER


def _render_managed_catalog(path: Path, entries: Sequence[Any]) -> bytes:
    old_headers, old_rows = _read_csv(path)
    headers = _headers_with_canonical(old_headers)
    by_directory = {
        (str(getattr(entry, "root_key", "")), str(getattr(entry, "relative_directory", ""))): entry
        for entry in entries
    }
    consumed: set[tuple[str, str]] = set()
    output: list[dict[str, Any]] = []
    for row in old_rows:
        root_key = row.get("本地根目录标识") or row.get("root_key")
        directory = row.get("本地作品目录") or row.get("relative_directory")
        key = (str(root_key or ""), str(directory or ""))
        entry = by_directory.get(key)
        if entry is None:
            # Preserve unknown user rows and their extra columns.
            output.append(row)
            continue
        output.append(_merge_row(row, archive_entry_csv_row(entry), headers))
        consumed.add(key)
    for key, entry in sorted(by_directory.items()):
        if key not in consumed:
            output.append(archive_entry_csv_row(entry))
    return _csv_bytes(headers, _scrub_public_csv_rows(output))


def _refresh_existing_legacy_aggregates(
    root_key: str,
    relative_directory: str,
    snapshots: Sequence[Mapping[str, Any]],
) -> None:
    """Refresh only existing 全部作品信息.csv files along this directory's ancestry."""
    parts = normalize_archive_relative_path(relative_directory).split("/")
    for depth in range(len(parts), -1, -1):
        ancestor = "/".join(parts[:depth])
        aggregate_relative = "/".join(part for part in (ancestor, "全部作品信息.csv") if part)
        aggregate_path = resolve_archive_path(root_key, aggregate_relative)
        if not aggregate_path.exists():
            continue
        scoped_entries = [
            _EntryView(row)
            for row in snapshots
            if row["root_key"] == root_key
            and (
                not ancestor
                or row["relative_directory"] == ancestor
                or str(row["relative_directory"]).startswith(ancestor + "/")
            )
        ]
        refreshed = refresh_legacy_csv(
            aggregate_path.read_bytes(), scoped_entries, root_key, per_media=True
        )
        _atomic_replace(root_key, aggregate_relative, refreshed)


def _content_conditions(entry: Any) -> list[Any]:
    conditions = [ArchiveEntry.id == entry["id"]]
    for field in _CONTENT_FIELDS:
        column = getattr(ArchiveEntry, field)
        value = entry.get(field)
        conditions.append(column.is_(None) if value is None else column == value)
    return conditions


def _return_detached(factory: Callable[[], Session], entry_id: int) -> ArchiveEntry:
    with factory() as db:
        entry = db.get(ArchiveEntry, entry_id)
        if entry is None:
            raise LookupError("Archive entry not found")
        db.expunge(entry)
        return entry


def _finalize_sync(
    factory: Callable[[], Session],
    entry_id: int,
    root_key: str,
    snapshot_entries: Sequence[Mapping[str, Any]],
) -> bool:
    expected = {int(row["id"]): _content_fingerprint(row) for row in snapshot_entries}
    with factory() as db:
        _begin_immediate(db)
        current = export_entries(db, filters={"root_key": root_key})
        current_snapshots = [_snapshot(row) for row in current]
        actual = {int(row["id"]): _content_fingerprint(row) for row in current_snapshots}
        if actual != expected:
            target = db.get(ArchiveEntry, entry_id)
            if target is not None:
                target.sync_status = "pending"
                target.sync_error = "Archive records changed during synchronization; retry required."
                db.commit()
            else:
                db.commit()
            return False

        target_snapshot = next((row for row in snapshot_entries if int(row["id"]) == entry_id), None)
        if target_snapshot is None:
            db.commit()
            return False
        now = now_iso()
        result = db.execute(
            update(ArchiveEntry)
            .where(*_content_conditions(target_snapshot))
            .values(sync_status="ready", sync_error=None, synced_at=now, updated_at=now)
        )
        db.commit()
        return result.rowcount == 1


def _persist_failure(
    factory: Callable[[], Session],
    entry_id: int,
    root_key: str | None,
    snapshot_entries: Sequence[Mapping[str, Any]],
    error: str,
    *,
    snapshot_complete: bool,
) -> None:
    snapshot_by_id = {int(row["id"]): _content_fingerprint(row) for row in snapshot_entries}
    with factory() as db:
        _begin_immediate(db)
        target = db.get(ArchiveEntry, entry_id)
        if target is None:
            db.commit()
            return
        changed = False
        if root_key and snapshot_complete:
            current = export_entries(db, filters={"root_key": root_key})
            current_by_id = {row.id: _content_fingerprint(_snapshot(row)) for row in current}
            changed = any(current_by_id.get(row_id) != fingerprint for row_id, fingerprint in snapshot_by_id.items())
            changed = changed or set(current_by_id) != set(snapshot_by_id)
        target.sync_status = "pending" if changed else "failed"
        target.sync_error = "Archive records changed during synchronization; retry required." if changed else error
        db.commit()


def sync_archive_entry(
    entry_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> ArchiveEntry:
    """Write all sidecars under a cross-process root lock and recover on failure.

    The service uses independent DB sessions. It commits ``pending`` before any
    replace, snapshots all root entries after locking, and conditionally marks
    ``ready`` only when the complete root snapshot is unchanged. A caller must
    commit its metadata/download intent before calling this function. It never
    copies, moves, deletes, or downloads media.
    """
    factory = _session_factory(session_factory)
    with factory() as identity_db:
        root_key = identity_db.execute(
            select(ArchiveEntry.root_key).where(ArchiveEntry.id == entry_id)
        ).scalar_one_or_none()
    if root_key is None:
        raise LookupError("Archive entry not found")

    snapshots: list[dict[str, Any]] = []
    snapshot_complete = False
    try:
        with _root_lock(root_key):
            with factory() as db:
                entry = db.get(ArchiveEntry, entry_id)
                if entry is None:
                    raise LookupError("Archive entry not found")
                entry.sync_status = "pending"
                entry.sync_error = None
                db.commit()

                # This complete snapshot happens only after acquiring the root
                # lock; session closes before file IO so SQLite readers do not
                # block later metadata commits.
                rows = export_entries(db, filters={"root_key": root_key})
                snapshots = [_snapshot(row) for row in rows]
                db.commit()
                snapshot_complete = True

            by_id = {int(row["id"]): row for row in snapshots}
            target = by_id.get(entry_id)
            if target is None:
                raise LookupError("Archive entry not found")
            # The requested work sidecar requires live media validation. Other
            # root entries remain represented in the catalog even when their
            # previously registered media is unavailable.
            _validate_entry_files(_EntryView(target))

            relative_directory = str(target["relative_directory"])
            info_dir = resolve_archive_path(root_key, relative_directory)
            info_dir.mkdir(parents=True, exist_ok=True)
            info_dir = resolve_archive_path(root_key, relative_directory)
            prior_csv_path = resolve_archive_path(root_key, _entry_relative_file(root_key, _EntryView(target), ARCHIVE_INFORMATION_FILES[0]))
            csv_payload, legacy_rows = _single_info_csv(root_key, _EntryView(target), prior_csv_path)
            info_row = _parse_csv_bytes(csv_payload)[1]
            json_payload = _render_info_json(_EntryView(target), [*legacy_rows, *info_row])
            markdown_payload = _render_markdown(_EntryView(target))

            _atomic_replace(root_key, _entry_relative_file(root_key, _EntryView(target), ARCHIVE_INFORMATION_FILES[0]), csv_payload)
            _atomic_replace(root_key, _entry_relative_file(root_key, _EntryView(target), ARCHIVE_INFORMATION_FILES[1]), json_payload)
            _atomic_replace(root_key, _entry_relative_file(root_key, _EntryView(target), ARCHIVE_INFORMATION_FILES[2]), markdown_payload)

            parent = _entry_directory_parent(_EntryView(target))
            collection_relative = _entry_relative_file(root_key, _EntryView({"relative_directory": parent}), ARCHIVE_COLLECTION_FILE)
            collection_path = resolve_archive_path(root_key, collection_relative)
            collection_entries = [
                _EntryView(row) for row in snapshots
                if row["root_key"] == root_key and _entry_directory_parent(_EntryView(row)) == parent
            ]
            if _is_managed_collection(root_key, parent, collection_path):
                old_headers, old_rows = _read_csv(collection_path)
                headers = _headers_with_canonical(old_headers)
                existing_by_directory = {
                    str(row.get("本地作品目录") or row.get("relative_directory") or ""): row
                    for row in old_rows
                }
                collection_rows = []
                for member in sorted(collection_entries, key=lambda row: (str(row.relative_directory).casefold(), row.id)):
                    prior = existing_by_directory.get(str(member.relative_directory), {})
                    collection_rows.append(_merge_row(prior, archive_entry_csv_row(member), headers))
                collection_bytes = _csv_bytes(headers, collection_rows)
                marker_relative = _entry_relative_file(root_key, _EntryView({"relative_directory": parent}), _COLLECTION_MARKER)
                marker_bytes = (json.dumps(_MANAGED_MARKER, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            else:
                collection_bytes = refresh_legacy_csv(collection_path.read_bytes(), collection_entries, root_key)
                marker_relative = None
                marker_bytes = b""
            if marker_relative:
                # Persist managed provenance first. If the CSV replace fails,
                # the next sync will still recognize and rebuild this collection.
                _atomic_replace(root_key, marker_relative, marker_bytes)
            _atomic_replace(root_key, collection_relative, collection_bytes)

            catalog_relative = ARCHIVE_CATALOG_FILE
            catalog_path = resolve_archive_path(root_key, catalog_relative)
            catalog_bytes = _render_managed_catalog(catalog_path, [_EntryView(row) for row in snapshots])
            _atomic_replace(root_key, catalog_relative, catalog_bytes)

            _refresh_existing_legacy_aggregates(
                root_key, relative_directory, snapshots
            )

            if not _finalize_sync(factory, entry_id, root_key, snapshots):
                return _return_detached(factory, entry_id)
            return _return_detached(factory, entry_id)
    except BaseException as exc:
        safe_error = _safe_error(exc)
        try:
            _persist_failure(
                factory,
                entry_id,
                root_key,
                snapshots,
                safe_error,
                snapshot_complete=snapshot_complete,
            )
        except Exception:
            # Preserve the original safe error for the caller; a later worker
            # can recover a still-pending row if the DB was unavailable too.
            pass
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise ArchiveSyncError(safe_error) from exc


class _EntryView:
    """Read-only attribute adapter for detached canonical snapshot dictionaries."""
    def __init__(self, values: Mapping[str, Any]):
        self.__dict__.update(values)
        if "files_json" not in self.__dict__ and "files" in self.__dict__:
            self.files_json = self.__dict__["files"]
        if "metadata_json" not in self.__dict__ and "metadata" in self.__dict__:
            self.metadata_json = self.__dict__["metadata"]

    @property
    def files(self):
        return getattr(self, "files_json", [])
