"""Canonical archive metadata, time provenance, and original media normalization."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
from pathlib import Path, PureWindowsPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import ARCHIVE_PLATFORM_LABELS
from app.schemas.archive import ArchiveEntrySchema
from app.utils.archive_paths import (
    normalize_archive_relative_path,
    relative_path_from_root,
    resolve_archive_path,
)


ARCHIVE_METADATA_VERSION = 1
_TIME_PRECISIONS = {"day", "minute", "second"}
_TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
_MEDIA_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".aiff", ".alac", ".avi", ".avif", ".bmp", ".f4v", ".flac", ".flv",
    ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".m4a", ".m4v", ".mkv",
    ".mov", ".mp3", ".mp4", ".m2ts", ".m2v", ".mjpeg", ".mpeg", ".mpg", ".oga", ".ogv", ".ogg", ".opus",
    ".png", ".qt", ".rm", ".rmvb", ".ts", ".tif", ".tiff", ".vob", ".wav",
    ".webm", ".webp", ".wma", ".wmv",
}
_DERIVED_DIRS = {
    "frames", "frame", "transcript", "transcripts", "notes", "note",
    "comment_images", "comment-images", "笔记", "转写", "关键帧", "抽帧",
}
_DERIVED_FILES = {
    "frame_manifest.json", "transcript.json", "transcript.txt", "transcript.srt",
    "作品信息.csv", "作品信息.json", "作品信息.md", "合集清单.csv",
    "归档总清单.csv",
}
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("作品标题", "标题", "title", "视频标题", "笔记标题"),
    "platform": ("平台代码", "平台", "platform", "source_platform"),
    "external_id": ("作品ID", "视频ID", "BVID", "笔记ID", "推文ID", "external_id", "video_id"),
    "url": ("平台链接", "作品链接", "原链接", "链接", "url", "link"),
    "published_at": ("发布时间（北京时间）", "发布时间", "发布时刻", "published_at", "publish_time"),
    "published_time_precision": ("发布时间精度", "发布精度", "published_time_precision"),
    "published_time_source": ("发布时间来源", "发布来源", "时间数据来源", "published_time_source"),
    "metadata_checked_at": ("信息核对时间（北京时间）", "信息核对时间", "metadata_checked_at"),
    "downloaded_at": ("下载完成时间（北京时间）", "下载完成时间", "下载时间", "downloaded_at", "download_time"),
    "download_time_source": ("下载时间来源", "download来源", "download_time_source"),
    "creator_label": ("博主", "作者", "UP主", "creator", "creator_name"),
    "group_label": ("分组", "分组名称", "group", "group_name"),
    "root_key": ("本地根目录标识", "根目录标识", "root_key"),
    "relative_directory": ("本地作品目录", "作品目录", "本地目录", "relative_directory"),
    "media_path": ("本地媒体路径", "本地媒体文件", "本地路径", "media_path", "local_path", "path"),
    "media_count": ("媒体数量", "media_count", "file_count"),
    "size_bytes": ("媒体大小（字节）", "文件大小", "size_bytes", "size"),
    "check_status": ("信息核对状态", "核对状态", "check_status"),
}
_CANONICAL_HEADER_ALIASES = {
    "归档ID": ("归档ID", "archive_id", "id"),
    "作品标题": _COLUMN_ALIASES["title"],
    "平台": ("平台", "platform_label"),
    "平台代码": ("平台代码", "platform", "source_platform"),
    "博主": _COLUMN_ALIASES["creator_label"],
    "分组": _COLUMN_ALIASES["group_label"],
    "作品ID": _COLUMN_ALIASES["external_id"],
    "平台链接": _COLUMN_ALIASES["url"],
    "发布时间（北京时间）": _COLUMN_ALIASES["published_at"],
    "发布时间精度": _COLUMN_ALIASES["published_time_precision"],
    "下载完成时间（北京时间）": _COLUMN_ALIASES["downloaded_at"],
    "发布时间来源": _COLUMN_ALIASES["published_time_source"],
    "下载时间来源": _COLUMN_ALIASES["download_time_source"],
    "信息核对状态": ("信息核对状态", "核对状态", "check_status"),
    "信息核对时间（北京时间）": ("信息核对时间（北京时间）", "信息核对时间", "metadata_checked_at"),
    "本地根目录标识": _COLUMN_ALIASES["root_key"],
    "本地作品目录": _COLUMN_ALIASES["relative_directory"],
    "本地媒体文件": ("本地媒体文件", "本地媒体路径", "media_path", "local_path", "path"),
    "媒体数量": _COLUMN_ALIASES["media_count"],
    "媒体大小（字节）": _COLUMN_ALIASES["size_bytes"],
    "备注": ("备注", "说明", "notes", "remark"),
}
CANONICAL_CSV_HEADERS = tuple(_CANONICAL_HEADER_ALIASES)
CANONICAL_HEADER_ALIASES = _CANONICAL_HEADER_ALIASES
LEGACY_COLUMN_ALIASES = _COLUMN_ALIASES


def _is_absolute_machine_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or text.startswith(("http://", "https://", "data:")):
        return False
    return bool(
        re.match(r"^[A-Za-z]:[\\/]", text)
        or text.startswith(("\\", "/"))
    )


def _is_private_legacy_column(name: str, value: Any) -> bool:
    key = str(name).casefold()
    is_path_column = any(token in key for token in ("path", "路径", "本地媒体", "file_path", "filepath"))
    if name in {"本地根目录标识", "本地作品目录", "本地媒体文件"} and not _is_absolute_machine_path(value):
        return False
    return is_path_column or _is_absolute_machine_path(value)


def split_legacy_columns(columns: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate safe custom CSV values from local path values kept only in DB."""
    public: dict[str, Any] = {}
    private: dict[str, Any] = {}
    for name, value in columns.items():
        target = private if _is_private_legacy_column(str(name), value) else public
        target[str(name)] = value
    return public, private


def public_archive_metadata(metadata: Any) -> dict[str, Any]:
    """Remove private local-path fields before sidecar/API metadata serialization.

    Task4 API handlers should call this helper instead of returning raw
    ``ArchiveEntry.metadata_json``. Canonical root-relative path fields remain
    in the ArchiveEntry schema; original legacy machine paths stay database-only.
    """
    raw = _mapping(metadata)

    def clean(value: Any, key: str = "") -> Any:
        if key.startswith("private_") or key in {"legacy_media_reference", "private_legacy_media_reference"}:
            return None
        if isinstance(value, Mapping):
            result = {}
            for child_key, child_value in value.items():
                if str(child_key).startswith("private_"):
                    continue
                if child_key in {"legacy_columns", "legacy_row"} and isinstance(child_value, Mapping):
                    safe_columns, _private_columns = split_legacy_columns(child_value)
                    result[child_key] = safe_columns
                    continue
                cleaned = clean(child_value, str(child_key))
                if cleaned is not None:
                    result[str(child_key)] = cleaned
            return result
        if isinstance(value, (list, tuple)):
            return [clean(item, key) for item in value]
        if _is_absolute_machine_path(value):
            return None
        return value

    cleaned = clean(raw)
    return cleaned if isinstance(cleaned, dict) else {}


def public_archive_url(value: Any) -> str | None:
    """Expose only external HTTP(S) links in canonical archive sidecars."""
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if clean.startswith(("https://", "http://")):
        return clean
    return None


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        result = value.model_dump(mode="python")
        return result if isinstance(result, dict) else {}
    if hasattr(value, "dict") and callable(value.dict):
        result = value.dict()
        return result if isinstance(result, dict) else {}
    return {}


def _parse_source_datetime(value: Any, source_timezone: str) -> tuple[datetime, bool]:
    try:
        source_zone = ZoneInfo(source_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("unknown source timezone") from exc
    if isinstance(value, datetime):
        parsed = value
        is_date_only = False
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
        is_date_only = True
    elif isinstance(value, str):
        raw = value.strip()
        if not raw or not _TIME_PATTERN.fullmatch(raw):
            raise ValueError("timestamp is not an ISO date or date-time")
        is_date_only = len(raw) == 10
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp is not an ISO date or date-time") from exc
    else:
        raise ValueError("timestamp must be an ISO string or date-time")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=source_zone)
    return parsed, is_date_only


def normalize_archive_time(
    value: Any,
    *,
    precision: str | None,
    source_timezone: str,
) -> tuple[str | None, str | None]:
    """Normalize a sourced timestamp to UTC without inventing second precision.

    If precision is absent, date-only input is conservatively ``day`` and any
    time-bearing input is ``minute``. Explicit day/minute inputs are truncated
    to their stated granularity before UTC conversion.
    """
    if value is None or value == "":
        return None, None
    if precision not in (None, *_TIME_PRECISIONS):
        raise ValueError("timestamp precision must be day, minute, or second")
    parsed, is_date_only = _parse_source_datetime(value, source_timezone)
    normalized_precision = precision if precision in _TIME_PRECISIONS else (
        "day" if is_date_only else "minute"
    )
    if normalized_precision == "day":
        source_local = parsed.astimezone(ZoneInfo(source_timezone))
        parsed = datetime.combine(source_local.date(), time.min, tzinfo=ZoneInfo(source_timezone))
    elif normalized_precision == "minute":
        parsed = parsed.replace(second=0, microsecond=0)
    else:
        parsed = parsed.replace(microsecond=0)
    utc_value = parsed.astimezone(timezone.utc)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ"), normalized_precision


def _display_time(value: str | None, precision: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local = parsed.astimezone(ZoneInfo("Asia/Shanghai"))
    except (ValueError, ZoneInfoNotFoundError):
        return ""
    if precision == "day":
        return local.strftime("%Y-%m-%d")
    if precision == "minute":
        return local.strftime("%Y-%m-%d %H:%M")
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _legacy_alias(row: Mapping[str, Any], field: str) -> Any:
    for alias in _COLUMN_ALIASES.get(field, ()):
        value = row.get(alias)
        if value not in (None, ""):
            return value
    return None


def normalize_legacy_csv_row(
    row: Mapping[str, Any],
    *,
    root_key: str,
    source_timezone: str = "Asia/Shanghai",
    source_name: str = "legacy_csv",
) -> dict[str, Any]:
    """Read a legacy row without fuzzy title matching or implied timestamp seconds."""
    platform = _legacy_alias(row, "platform")
    platform_map = {label: code for code, label in ARCHIVE_PLATFORM_LABELS.items()}
    platform_map.update({
        "Twitter/X": "twitter",
        "B站": "bilibili",
        "哔哩哔哩（B站）": "bilibili",
        "推特": "twitter",
    })
    if platform in platform_map:
        platform = platform_map[platform]

    published_raw = _legacy_alias(row, "published_at")
    published_precision = _legacy_alias(row, "published_time_precision")
    try:
        published_at, published_precision = normalize_archive_time(
            published_raw,
            precision=str(published_precision) if published_precision else None,
            source_timezone=source_timezone,
        ) if published_raw else (None, None)
    except ValueError:
        published_at, published_precision = None, None
    downloaded_raw = _legacy_alias(row, "downloaded_at")
    try:
        download_at, download_precision = normalize_archive_time(
            downloaded_raw,
            precision=None,
            source_timezone=source_timezone,
        ) if downloaded_raw else (None, None)
    except ValueError:
        download_at, download_precision = None, None
    checked_raw = _legacy_alias(row, "metadata_checked_at")
    try:
        checked_at, _checked_precision = normalize_archive_time(
            checked_raw,
            precision=None,
            source_timezone=source_timezone,
        ) if checked_raw else (None, None)
    except ValueError:
        checked_at = None
    check_status = _legacy_alias(row, "check_status") or "needs_review"
    check_status = {
        "已核实": "verified",
        "已验证": "verified",
        "待核实": "needs_review",
        "同名作品按清单编号对应": "needs_review",
    }.get(str(check_status), check_status)
    if check_status not in {"verified", "needs_review", "conflict", "failed"}:
        check_status = "needs_review"

    result = {
        "root_key": root_key,
        "platform": platform,
        "external_id": _legacy_alias(row, "external_id"),
        "title": _legacy_alias(row, "title"),
        "url": _legacy_alias(row, "url"),
        "creator_label": _legacy_alias(row, "creator_label"),
        "group_label": _legacy_alias(row, "group_label"),
        "published_at": published_at,
        "published_time_precision": published_precision,
        "published_time_source": (_legacy_alias(row, "published_time_source") or source_name) if published_at else None,
        "downloaded_at": download_at,
        "download_time_precision": download_precision,
        "download_time_source": (_legacy_alias(row, "download_time_source") or source_name) if download_at else None,
        "check_status": check_status,
        "metadata_checked_at": checked_at,
        "legacy_columns": dict(row),
        "source_timezone": source_timezone,
    }
    raw_relative = _legacy_alias(row, "relative_directory") or _legacy_alias(row, "media_path")
    if raw_relative:
        result["legacy_media_reference"] = str(raw_relative)
    return result


def _provenance_mapping(
    value: Any,
    *,
    source_context: Mapping[str, Any],
    field_name: str,
) -> dict[str, Any]:
    explicit = _mapping(value)
    context_value = source_context.get(field_name)
    context = _mapping(context_value)
    merged = dict(context)
    merged.update({key: item for key, item in explicit.items() if item is not None})
    prefix = "published" if field_name == "publication" else "download"
    aliases = {
        "source": (f"{prefix}_time_source", "source"),
        "precision": (f"{prefix}_time_precision", "precision"),
        "timezone": (f"{prefix}_timezone", "timezone"),
        "value": ((f"{prefix}_at", "completed_at", "value") if field_name == "download" else (f"{prefix}_at", "value")),
        "verified": (f"{prefix}_verified", "verified"),
        "check_status": ("check_status",),
        "checked_at": ("metadata_checked_at", "checked_at"),
    }
    for output, names in aliases.items():
        if merged.get(output) not in (None, ""):
            continue
        for name in (*names, output):
            if source_context.get(name) not in (None, ""):
                merged[output] = source_context[name]
                break
    return merged


def _existing_value(existing: Any, key: str, default: Any = None) -> Any:
    if existing is None:
        return default
    aliases = {
        "metadata_json": ("metadata_json", "metadata"),
        "files_json": ("files_json", "files"),
    }
    for name in aliases.get(key, (key,)):
        value = _value(existing, name, None)
        if value is not None:
            return value
    return default


def _normalize_time_candidate(
    provenance: Mapping[str, Any],
    fallback_value: Any,
    *,
    fallback_source: Any,
    fallback_precision: Any,
    default_timezone: str,
) -> tuple[str | None, str | None, str | None, str, bool, str | None, str | None]:
    raw_value = provenance.get("value", fallback_value)
    source = provenance.get("source", fallback_source)
    raw_precision = provenance.get("precision", fallback_precision)
    source_timezone = str(provenance.get("timezone") or default_timezone)
    status = str(provenance.get("check_status") or "")
    verified = (provenance.get("verified") is True or status == "verified") and bool(source)
    checked_at = provenance.get("checked_at")
    failed = status in {"failed", "conflict"} or provenance.get("failed") is True
    if raw_value in (None, "") or failed:
        return None, source if raw_value else None, raw_precision if raw_value else None, source_timezone, verified, str(checked_at) if checked_at else None, status or None
    normalized, precision = normalize_archive_time(
        raw_value,
        precision=str(raw_precision) if raw_precision else None,
        source_timezone=source_timezone,
    )
    return normalized, str(source) if source not in (None, "") else None, precision, source_timezone, verified, str(checked_at) if checked_at else None, status or None


def _identity_conflict(existing: Any, incoming_status: str | None) -> bool:
    return bool(incoming_status == "conflict")


def _precision_rank(value: str | None) -> int:
    return {"day": 1, "minute": 2, "second": 3}.get(value or "", 0)


def _same_precision_bucket(
    old_value: str,
    old_precision: str | None,
    new_value: str,
    *,
    source_timezone: str = "Asia/Shanghai",
) -> bool:
    """Treat a verified finer timestamp in the same old day/minute as compatible."""
    try:
        old = datetime.fromisoformat(old_value.replace("Z", "+00:00"))
        new = datetime.fromisoformat(new_value.replace("Z", "+00:00"))
        if old.tzinfo is None:
            old = old.replace(tzinfo=timezone.utc)
        if new.tzinfo is None:
            new = new.replace(tzinfo=timezone.utc)
        zone = ZoneInfo(source_timezone)
        old_local = old.astimezone(zone)
        new_local = new.astimezone(zone)
    except (ValueError, ZoneInfoNotFoundError):
        return False
    if old_precision == "day":
        return old_local.date() == new_local.date()
    if old_precision == "minute":
        return old_local.replace(second=0, microsecond=0) == new_local.replace(second=0, microsecond=0)
    if old_precision == "second":
        return old_local.replace(microsecond=0) == new_local.replace(microsecond=0)
    return old_local == new_local


def _clean_media_item_name(value: Any) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _is_derived(relative_path: str, *, media_directory: str | None = None) -> bool:
    normalized = relative_path.replace("\\", "/")
    scoped = normalized
    if media_directory:
        prefix = media_directory.replace("\\", "/").rstrip("/")
        if os.path.normcase(normalized).startswith(os.path.normcase(prefix + "/")):
            scoped = normalized[len(prefix) + 1:]
        elif os.path.normcase(normalized) == os.path.normcase(prefix):
            scoped = normalized.rsplit("/", 1)[-1]
    parts = [part.casefold() for part in scoped.split("/")]
    if any(part in _DERIVED_DIRS for part in parts[:-1]):
        return True
    filename = parts[-1] if parts else ""
    suffix = Path(filename).suffix.casefold()
    if media_directory:
        relative = relative_path.replace("\\", "/").casefold()
        work_root = media_directory.replace("\\", "/").rstrip("/").casefold()
        if relative in {f"{work_root}/cover.jpg", f"{work_root}/cover.png"}:
            return True
        if relative == work_root and filename in {"cover.jpg", "cover.png"}:
            return True
    return filename in _DERIVED_FILES or suffix in {".part", ".tmp", ".temp", ".srt", ".vtt"}


def _file_mapping(item: Any) -> dict[str, Any]:
    mapped = _mapping(item)
    if mapped:
        return mapped
    if isinstance(item, (str, os.PathLike)):
        return {"relative_path": os.fspath(item)}
    # DownloadResult.MediaFile is an immutable dataclass; read its public receipt
    # fields without importing the pipeline layer into archive services.
    values = {}
    for key in ("relative_path", "path", "file_path", "name", "size_bytes", "media_type", "sha256"):
        if hasattr(item, key):
            values[key] = getattr(item, key)
    if values:
        return values
    return {}


def _candidate_file_path(
    item: Any,
    *,
    root_key: str,
    relative_directory: str,
    media_directory: str,
) -> tuple[str, dict[str, Any]]:
    info = _file_mapping(item)
    raw = info.get("relative_path") or info.get("path") or info.get("file_path") or info.get("name")
    if isinstance(raw, os.PathLike):
        raw = os.fspath(raw)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Media file must identify a root-relative file")
    raw = raw.strip()
    if Path(raw).is_absolute() or PureWindowsPath(raw).drive or raw.startswith(("\\\\", "//")):
        relative = relative_path_from_root(root_key, raw)
    else:
        normalized = normalize_archive_relative_path(raw)
        if normalized == media_directory or normalized.startswith(media_directory.rstrip("/") + "/"):
            relative = normalized
        elif "/" not in normalized:
            relative = f"{media_directory.rstrip('/')}/{normalized}" if media_directory else normalized
        else:
            # Explicit paths containing a slash are interpreted as root-relative;
            # the path resolver below rejects non-existing or out-of-root values.
            relative = normalized
    relative = normalize_archive_relative_path(relative)
    media_prefix = media_directory.rstrip("/") + "/"
    if media_directory and relative != media_directory and not relative.startswith(media_prefix):
        raise ValueError("Registered media must remain inside the stored Work media path")
    return relative, info


def _enumerate_media_files(
    work: Any,
    *,
    root_key: str,
    relative_directory: str,
    downloaded_files: Sequence[Any] | None,
) -> list[dict[str, Any]]:
    stored_media_path = _value(work, "media_path")
    if stored_media_path:
        media_directory = relative_path_from_root(root_key, str(stored_media_path))
    else:
        media_directory = relative_directory
    media_path = resolve_archive_path(root_key, media_directory)

    if downloaded_files is not None:
        candidates = list(downloaded_files)
    elif str(_value(work, "content_type") or "video").casefold() == "text":
        candidates = []
    else:
        candidates = []
        if media_path.is_file():
            candidates = [media_directory]
        elif media_path.is_dir():
            for current, dirs, files in os.walk(media_path, followlinks=False):
                current_path = Path(current)
                safe_dirs = []
                for dirname in dirs:
                    child = current_path / dirname
                    rel = child.relative_to(resolve_archive_path(root_key, "", allow_root=True)).as_posix()
                    try:
                        checked = resolve_archive_path(root_key, rel)
                    except (ValueError, OSError):
                        continue
                    if dirname.casefold() not in _DERIVED_DIRS and checked.is_dir():
                        safe_dirs.append(dirname)
                dirs[:] = safe_dirs
                for filename in files:
                    candidate = current_path / filename
                    if candidate.suffix.casefold() not in _MEDIA_EXTENSIONS:
                        continue
                    rel = candidate.relative_to(resolve_archive_path(root_key, "", allow_root=True)).as_posix()
                    candidates.append(rel)

    normalized: dict[str, dict[str, Any]] = {}
    for item in candidates:
        relative, info = _candidate_file_path(
            item,
            root_key=root_key,
            relative_directory=relative_directory,
            media_directory=media_directory,
        )
        if _is_derived(relative, media_directory=media_directory):
            continue
        if Path(relative).suffix.casefold() not in _MEDIA_EXTENSIONS:
            continue
        file_path = resolve_archive_path(root_key, relative, must_exist=True)
        if not file_path.is_file():
            raise ValueError("Registered media path is not a file")
        try:
            file_path.relative_to(media_path if media_path.is_dir() else media_path.parent)
        except ValueError as exc:
            raise ValueError("Registered media is outside the stored Work media path") from exc
        size = file_path.stat().st_size
        if size <= 0:
            raise ValueError("Original media must contain bytes")
        receipt_size = info.get("size_bytes")
        if downloaded_files is not None and receipt_size is not None:
            try:
                if int(receipt_size) != size:
                    raise ValueError("Download receipt size no longer matches the registered media")
            except (TypeError, ValueError) as exc:
                raise ValueError("Download receipt size is invalid or stale") from exc
        file_id = "f_" + hashlib.sha256(f"{root_key}\0{relative}".encode("utf-8")).hexdigest()[:32]
        normalized[relative] = {
            "file_id": file_id,
            "relative_path": relative,
            "name": _clean_media_item_name(info.get("name") or file_path.name),
            "size_bytes": size,
            "media_type": (
                info.get("media_type")
                if isinstance(info.get("media_type"), str) and "/" in info["media_type"]
                else mimetypes.guess_type(file_path.name)[0]
            ),
            "sha256": info.get("sha256") if isinstance(info.get("sha256"), str) else None,
        }
    return [normalized[path] for path in sorted(normalized, key=str.casefold)]


def build_archive_metadata(
    work: Any,
    root_key: str,
    relative_directory: str,
    downloaded_files: Sequence[Any] | None = None,
    *,
    existing: Any = None,
    publication_provenance: Mapping[str, Any] | None = None,
    download_provenance: Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
    legacy_columns: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an ArchiveEntry upsert payload with explicit sources and file evidence.

    `source_context` defaults Work timestamps to the database's UTC storage
    contract. Legacy CSV importers should pass `Asia/Shanghai`; resolver results
    should pass `publication_provenance` with ``value``, ``source``,
    ``timezone``, ``precision``, and an explicit ``verified``/``check_status``.
    Existing verified values survive absent, failed, or conflicting candidates.
    """
    context = dict(source_context or {})
    normalized_directory = normalize_archive_relative_path(relative_directory)
    # Resolve the directory before interpreting any registered media paths.
    resolve_archive_path(root_key, normalized_directory)

    previous_metadata = _mapping(_existing_value(existing, "metadata_json", {}))
    old_status = _value(existing, "check_status", "needs_review") if existing is not None else "needs_review"
    old_trustworthy = old_status == "verified"
    initial_provenance = _mapping(publication_provenance)
    publication = _provenance_mapping(
        publication_provenance,
        source_context=context,
        field_name="publication",
    )
    download = _provenance_mapping(
        download_provenance,
        source_context=context,
        field_name="download",
    )
    identity_conflict = _identity_conflict(
        existing,
        str(publication.get("check_status") or initial_provenance.get("check_status") or ""),
    )

    pub_raw = publication.get("value", _value(work, "published_at"))
    pub_source = publication.get("source", _value(work, "published_time_source"))
    pub_precision = publication.get("precision", _value(work, "published_time_precision"))
    pub_tz = str(
        publication.get("timezone")
        or context.get("published_timezone")
        or context.get("source_timezone")
        or "UTC"
    )
    try:
        pub_candidate = _normalize_time_candidate(
            {**publication, "source": pub_source, "precision": pub_precision, "value": pub_raw},
            None,
            fallback_source=pub_source,
            fallback_precision=pub_precision,
            default_timezone=pub_tz,
        )
    except ValueError:
        pub_candidate = (None, None, None, pub_tz, False, None, "failed")
    new_pub, new_pub_source, new_pub_precision, pub_source_timezone, pub_verified, pub_checked, pub_status = pub_candidate

    work_downloaded = _value(work, "downloaded_at")
    work_download_source = _value(work, "download_time_source")
    download_disposition = download.get("disposition")
    if download_disposition in {"reused", "not_required"}:
        # Reuse does not create a new receipt; text-only works have no receipt.
        download_raw = download_source = download_precision = None
    else:
        download_raw = download.get("value", work_downloaded)
        download_source = download.get("source", work_download_source)
        download_precision = download.get("precision", _value(work, "download_time_precision"))
    download_tz = str(
        download.get("timezone")
        or context.get("download_timezone")
        or context.get("source_timezone")
        or "UTC"
    )
    # A persisted download receipt with a source records an actual event at
    # second precision. Legacy inputs must supply their observed precision.
    if download_precision is None and download_source:
        download_precision = "second"
    try:
        download_candidate = _normalize_time_candidate(
            {**download, "source": download_source, "precision": download_precision, "value": download_raw},
            None,
            fallback_source=download_source,
            fallback_precision=download_precision,
            default_timezone=download_tz,
        )
    except ValueError:
        download_candidate = (None, None, None, download_tz, False, None, "failed")
    new_download, new_download_source, new_download_precision, download_source_timezone, download_verified, download_checked, download_status = download_candidate
    if new_download and not new_download_source:
        # A clock-shaped value without a receipt source is not evidence of a
        # completed write; keep any prior sourced receipt below.
        new_download, new_download_precision, download_verified = None, None, False
    download_failed = download_status in {"failed", "conflict"} or download.get("failed") is True
    new_download_receipt = bool(
        download_disposition == "downloaded"
        and new_download
        and new_download_source
        and download_verified
        and not download_failed
    )

    old_pub = _value(existing, "published_at")
    old_download = _value(existing, "downloaded_at")
    old_pub_source = _value(existing, "published_time_source")
    old_download_source = _value(existing, "download_time_source")
    old_pub_precision = _value(existing, "published_time_precision")
    old_download_precision = _value(existing, "download_time_precision")
    old_provenance = _mapping(previous_metadata.get("provenance"))
    old_published_provenance = _mapping(old_provenance.get("published_at"))
    old_download_provenance = _mapping(old_provenance.get("downloaded_at"))
    old_pub_timezone = str(old_published_provenance.get("source_timezone") or "Asia/Shanghai")
    old_download_timezone = str(old_download_provenance.get("source_timezone") or "Asia/Shanghai")

    # A fresh authoritative minute/second value may refine a legacy day/minute
    # value only when both land in the old value's stated precision bucket.
    pub_compare_precision = (
        new_pub_precision if _precision_rank(old_pub_precision) > _precision_rank(new_pub_precision)
        else old_pub_precision
    )
    pub_precision_compatible = bool(
        old_pub and new_pub
        and _same_precision_bucket(
            str(old_pub), pub_compare_precision, new_pub, source_timezone=old_pub_timezone
        )
    )
    download_compare_precision = (
        new_download_precision if _precision_rank(old_download_precision) > _precision_rank(new_download_precision)
        else old_download_precision
    )
    download_precision_compatible = bool(
        old_download and new_download
        and _same_precision_bucket(
            str(old_download), download_compare_precision, new_download,
            source_timezone=old_download_timezone,
        )
    )
    pub_precision_conflict = bool(
        old_trustworthy
        and old_pub
        and new_pub
        and pub_verified
        and not pub_precision_compatible
    )
    download_precision_conflict = bool(
        old_trustworthy
        and old_download
        and new_download
        and download_verified
        and not download_precision_compatible
        and not new_download_receipt
    )
    keep_more_precise_published = bool(
        old_trustworthy
        and old_pub
        and new_pub
        and pub_verified
        and _precision_rank(old_pub_precision) > _precision_rank(new_pub_precision)
        and pub_precision_compatible
    )

    pub_failed = pub_status in {"failed", "conflict"} or publication.get("failed") is True
    preserve_published = (
        identity_conflict or pub_failed or not new_pub
        or (old_trustworthy and not pub_verified)
        or pub_precision_conflict or keep_more_precise_published
    )
    preserve_downloaded = (
        download_failed or not new_download or download_precision_conflict
        or (old_trustworthy and bool(old_download) and not download_verified)
    )
    if preserve_published:
        published_at, published_source, published_precision = old_pub, old_pub_source, old_pub_precision
    else:
        published_at, published_source, published_precision = new_pub, new_pub_source, new_pub_precision
    if preserve_downloaded:
        downloaded_at, downloaded_source, downloaded_precision = old_download, old_download_source, old_download_precision
    else:
        downloaded_at, downloaded_source, downloaded_precision = new_download, new_download_source, new_download_precision

    explicit_status = str(
        publication.get("check_status") or context.get("check_status") or ""
    )
    if (
        identity_conflict or explicit_status == "conflict" or pub_status == "conflict"
        or download_status == "conflict" or pub_precision_conflict or download_precision_conflict
    ):
        check_status = "conflict"
    elif explicit_status == "failed" or pub_status == "failed" or download_status == "failed":
        check_status = "failed"
    elif (publication.get("verified") is True or publication.get("check_status") == "verified") and new_pub_source:
        check_status = "verified" if published_at else "needs_review"
    elif existing is not None:
        check_status = old_status
    else:
        check_status = "needs_review"

    # A failed lookup may update the last status without deleting prior values.
    if existing is not None and old_trustworthy and published_at and check_status == "needs_review":
        check_status = old_status

    def chosen_identity(field: str, *, required: bool = False):
        incoming = _value(work, field)
        prior = _value(existing, field)
        if identity_conflict or (check_status in {"failed", "conflict"} and prior not in (None, "")):
            selected = prior if prior not in (None, "") else incoming
        else:
            selected = incoming if incoming not in (None, "") else prior
        if required and selected in (None, ""):
            raise ValueError(f"Archive metadata requires {field}")
        return selected

    platform = chosen_identity("platform", required=True)
    title = chosen_identity("title", required=True)
    external_id = chosen_identity("external_id")
    url = chosen_identity("url")
    creator = _value(work, "creator")
    group = _value(work, "group")
    creator_id = _value(work, "creator_id")
    if creator_id is None:
        creator_id = _value(existing, "creator_id")
    creator_label = _value(work, "creator_label") or _value(creator, "name") or _value(existing, "creator_label")
    group_id = _value(work, "group_id")
    if group_id is None:
        group_id = _value(existing, "group_id")
    group_label = _value(work, "group_label") or _value(group, "name") or _value(existing, "group_label")

    checked_at = publication.get("checked_at") or publication.get("metadata_checked_at") or context.get("metadata_checked_at")
    if checked_at not in (None, ""):
        try:
            checked_at, _checked_precision = normalize_archive_time(
                checked_at,
                precision=publication.get("checked_precision") or context.get("metadata_checked_precision"),
                source_timezone=pub_tz,
            )
        except ValueError:
            checked_at = None
    if checked_at is None:
        checked_at = _value(existing, "metadata_checked_at")

    old_meta = previous_metadata
    old_legacy = _mapping(old_meta.get("legacy_columns"))
    old_legacy.update(_mapping(old_meta.get("private_legacy_columns")))
    incoming_legacy = dict(legacy_columns or {})
    incoming_legacy.update(_mapping(context.get("legacy_columns")))
    merged_legacy = dict(old_legacy)
    for key, value in incoming_legacy.items():
        if value not in (None, "") or key not in merged_legacy:
            merged_legacy[str(key)] = value
    public_legacy, private_legacy = split_legacy_columns(merged_legacy)

    pub_provenance = {
        "source": published_source,
        "source_timezone": pub_source_timezone,
        "precision": published_precision,
        "verified": bool((pub_verified and not preserve_published) or (preserve_published and old_trustworthy)),
    }
    if preserve_published and old_published_provenance:
        pub_provenance = dict(old_published_provenance)
    elif pub_checked:
        pub_provenance["checked_at"] = pub_checked
    download_provenance_record = {
        "source": downloaded_source,
        "source_timezone": download_source_timezone,
        "precision": downloaded_precision,
        "verified": bool((download_verified and not preserve_downloaded) or (preserve_downloaded and old_trustworthy)),
    }
    if preserve_downloaded and old_download_provenance:
        download_provenance_record = dict(old_download_provenance)
    elif download_checked:
        download_provenance_record["checked_at"] = download_checked
    provenance = old_provenance
    provenance.update({
        "published_at": {**_mapping(provenance.get("published_at")), **pub_provenance},
        "downloaded_at": {**_mapping(provenance.get("downloaded_at")), **download_provenance_record},
    })
    metadata_json = {
        **old_meta,
        "schema_version": ARCHIVE_METADATA_VERSION,
        "provenance": provenance,
    }
    content_type = _value(work, "content_type")
    if content_type not in (None, ""):
        metadata_json["content_type"] = str(content_type)
    if public_legacy:
        metadata_json["legacy_columns"] = public_legacy
    elif "legacy_columns" in metadata_json:
        metadata_json.pop("legacy_columns", None)
    if private_legacy:
        metadata_json["private_legacy_columns"] = private_legacy
    elif "private_legacy_columns" in metadata_json:
        metadata_json.pop("private_legacy_columns", None)
    if context.get("legacy_media_reference") not in (None, ""):
        # Preserve the original historical reference for refresh matching, but
        # keep it private so it cannot leak through the metadata DTO.
        metadata_json["private_legacy_media_reference"] = context["legacy_media_reference"]
    for key in ("legacy_media_reference",):
        value = _value(work, key)
        if value not in (None, ""):
            metadata_json[f"private_{key}"] = value

    files_json = _enumerate_media_files(
        work,
        root_key=root_key,
        relative_directory=normalized_directory,
        downloaded_files=downloaded_files,
    )
    prior_files = _existing_value(existing, "files_json", []) or []
    if not files_json and existing is not None and downloaded_files is None:
        # A transient missing directory/list must not erase previously verified
        # file registrations. Each prior path is revalidated before preservation.
        for raw_file in prior_files:
            item = _mapping(raw_file)
            rel = item.get("relative_path")
            if not isinstance(rel, str):
                continue
            checked = resolve_archive_path(root_key, rel, must_exist=True)
            files_json.append({
                "file_id": item.get("file_id") or "f_" + hashlib.sha256(f"{root_key}\0{rel}".encode("utf-8")).hexdigest()[:32],
                "relative_path": rel,
                "name": item.get("name") or checked.name,
                "size_bytes": checked.stat().st_size,
                "media_type": item.get("media_type") or mimetypes.guess_type(checked.name)[0],
                "sha256": item.get("sha256"),
            })

    return {
        "root_key": root_key,
        "relative_directory": normalized_directory,
        "work_id": _value(work, "id", _value(existing, "work_id")),
        "platform": platform,
        "external_id": external_id,
        "title": title,
        "url": url,
        "creator_id": creator_id,
        "creator_label": creator_label,
        "group_id": group_id,
        "group_label": group_label,
        "published_at": published_at,
        "published_time_source": published_source,
        "published_time_precision": published_precision,
        "downloaded_at": downloaded_at,
        "download_time_source": downloaded_source,
        "download_time_precision": downloaded_precision,
        "metadata_checked_at": checked_at,
        "check_status": check_status,
        "metadata_version": ARCHIVE_METADATA_VERSION,
        "metadata_json": metadata_json,
        "files_json": files_json,
        "sync_status": "pending",
        "sync_error": None,
    }


def archive_entry_payload(entry: Any) -> dict[str, Any]:
    """Return the exact public ArchiveEntry field names used in sidecar JSON."""
    payload = ArchiveEntrySchema.model_validate(entry).model_dump(mode="json")
    payload["metadata"] = public_archive_metadata(payload.get("metadata"))
    payload["url"] = public_archive_url(payload.get("url"))
    try:
        payload["relative_directory"] = normalize_archive_relative_path(payload["relative_directory"])
    except (TypeError, ValueError):
        payload["relative_directory"] = ""
    public_files = []
    for item in payload.get("files", []):
        relative = item.get("relative_path")
        try:
            safe_relative = normalize_archive_relative_path(relative)
        except (TypeError, ValueError):
            continue
        media_type = item.get("media_type")
        if not isinstance(media_type, str) or "/" not in media_type:
            media_type = mimetypes.guess_type(str(item.get("name") or safe_relative))[0]
        public_files.append({
            **item,
            "file_id": "f_" + hashlib.sha256(
                f"{payload['root_key']}\0{safe_relative}".encode("utf-8")
            ).hexdigest()[:32],
            "relative_path": safe_relative,
            "name": _clean_media_item_name(item.get("name") or safe_relative),
            "media_type": media_type,
        })
    payload["files"] = public_files
    return payload


def archive_entry_csv_row(entry: Any) -> dict[str, Any]:
    """Render one canonical aggregate row; file names are root-relative."""
    raw_files = _value(entry, "files_json", _value(entry, "files", [])) or []
    files = []
    for raw in raw_files:
        item = _mapping(raw)
        try:
            item["relative_path"] = normalize_archive_relative_path(item.get("relative_path"))
        except (TypeError, ValueError):
            continue
        files.append(item)
    platform = _value(entry, "platform", "") or ""
    metadata_checked = _value(entry, "metadata_checked_at")
    row = {
        "归档ID": _value(entry, "id", ""),
        "作品标题": _value(entry, "title", "") or "",
        "平台": ARCHIVE_PLATFORM_LABELS.get(platform, platform),
        "平台代码": platform,
        "博主": _value(entry, "creator_label", "") or "",
        "分组": _value(entry, "group_label", "") or "",
        "作品ID": _value(entry, "external_id", "") or "",
        "平台链接": public_archive_url(_value(entry, "url")) or "",
        "发布时间（北京时间）": _display_time(_value(entry, "published_at"), _value(entry, "published_time_precision")),
        "发布时间精度": _value(entry, "published_time_precision", "") or "",
        "下载完成时间（北京时间）": _display_time(_value(entry, "downloaded_at"), _value(entry, "download_time_precision")),
        "发布时间来源": _value(entry, "published_time_source", "") or "",
        "下载时间来源": _value(entry, "download_time_source", "") or "",
        "信息核对状态": _value(entry, "check_status", "needs_review") or "needs_review",
        "信息核对时间（北京时间）": _display_time(metadata_checked, "second"),
        "本地根目录标识": _value(entry, "root_key", "") or "",
        "本地作品目录": _value(entry, "relative_directory", "") or "",
        "本地媒体文件": "\n".join(str(item.get("relative_path", "")) for item in files if item.get("relative_path")),
        "媒体数量": len(files),
        "媒体大小（字节）": sum(int(item.get("size_bytes") or 0) for item in files),
        "备注": "",
    }
    return row


def markdown_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
