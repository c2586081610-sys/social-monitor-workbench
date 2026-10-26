"""Safe, idempotent indexing of existing media directories.

The scanner records what an allowlisted root already contains.  It never
creates Works or download Tasks, and it treats per-file rows as evidence for a
physical directory rather than assigning one row's identity to every file.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ARCHIVE_PLATFORM_LABELS
from app.models import ArchiveEntry, Work
from app.models.archive_entry import physical_directory_key
from app.services.archive_metadata_service import (
    LEGACY_COLUMN_ALIASES,
    build_archive_metadata,
    normalize_legacy_csv_row,
    split_legacy_columns,
)
from app.utils.archive_paths import normalize_archive_relative_path, relative_path_from_root, resolve_archive_path


_MEDIA_EXTENSIONS = {
    ".3g2", ".3gp", ".aac", ".aiff", ".alac", ".avi", ".avif", ".bmp", ".f4v", ".flac", ".flv",
    ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".m4a", ".m4v", ".mkv", ".mov", ".mp3",
    ".mp4", ".m2ts", ".m2v", ".mjpeg", ".mpeg", ".mpg", ".oga", ".ogv", ".ogg", ".opus",
    ".png", ".qt", ".rm", ".rmvb", ".ts", ".tif", ".tiff", ".vob", ".wav", ".webm",
    ".webp", ".wma", ".wmv",
}
_DERIVED_DIRS = {
    "frames", "frame", "transcript", "transcripts", "notes", "note",
    "comment_images", "comment-images", "笔记", "转写", "关键帧", "抽帧",
}
_DERIVED_FILES = {
    "frame_manifest.json", "transcript.json", "transcript.txt", "transcript.srt",
    "作品信息.csv", "作品信息.json", "作品信息.md", "合集清单.csv", "归档总清单.csv",
    "cover.jpg", "cover.png",
}
_EVIDENCE_FILES = {
    "作品信息.csv", "作品信息.json", "全部作品信息.csv", "合集清单.csv", "归档总清单.csv",
}
_MAX_VISITED_DIRECTORIES = 20_000
_MAX_EVIDENCE_FILES = 5_000
_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
_MAX_ROWS_PER_EVIDENCE = 20_000
_MAX_DEPTH = 48
_MAX_MEDIA_PER_DIRECTORY = 2_000
_REPARSE_POINT = 0x0400
_PLATFORM_LABEL_TO_CODE = {label.casefold(): code for code, label in ARCHIVE_PLATFORM_LABELS.items()}
_PLATFORM_LABEL_TO_CODE.update({
    "b站": "bilibili", "哔哩哔哩（b站）": "bilibili", "哔哩哔哩(b站)": "bilibili",
    "推特/x": "twitter", "twitter/x": "twitter", "x": "twitter",
})
_KNOWN_PLATFORMS = set(ARCHIVE_PLATFORM_LABELS)
_SENSITIVE_KEY = re.compile(r"(?:cookie|token|password|passwd|authorization|credential|secret|session[_-]?id)", re.I)
_BVID = re.compile(r"^BV[0-9A-Za-z]{10}$")
_AVID = re.compile(r"^av[1-9][0-9]{0,18}$", re.I)
_URL_ID_PATTERNS = {
    "bilibili": re.compile(r"(?:^|/)video/(BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,18})(?:/|$)", re.I),
    "douyin": re.compile(r"/(?:video|share/video)/([0-9]{8,30})(?:/|$)"),
    "xhs": re.compile(r"/(?:explore|discovery/item)/([A-Za-z0-9_-]{6,128})(?:/|$)"),
    "twitter": re.compile(r"/(?:i/web/)?status/([0-9]{5,25})(?:/|$)"),
}
_PLATFORM_HOSTS = {
    "bilibili": {"bilibili.com", "b23.tv"},
    "douyin": {"douyin.com", "iesdouyin.com"},
    "xhs": {"xiaohongshu.com", "xhslink.com"},
    "twitter": {"x.com", "twitter.com", "t.co"},
    "wechat": {"mp.weixin.qq.com", "weixin.qq.com"},
}


class ScanPlanError(RuntimeError):
    """A scan could not create a deterministic safe directory plan."""


class DirectoryScanError(RuntimeError):
    """A per-directory failure with a path-free public code."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True)
class ScanPlan:
    root_key: str
    relative_directory: str
    directories: tuple[str, ...]
    evidence_files: tuple[str, ...]
    unsupported_directories: tuple[str, ...] = ()
    truncated: bool = False
    enumeration_errors: tuple[dict[str, str], ...] = ()

    def as_cursor(self) -> dict[str, Any]:
        return {
            "version": 1,
            "initialized": True,
            "directories": list(self.directories),
            "evidence_files": list(self.evidence_files),
            "unsupported_directories": list(self.unsupported_directories),
            "enumeration_errors": list(self.enumeration_errors),
            "truncated": self.truncated,
            "next_index": 0,
            "directory_attempts": {},
            "failed_directories": [],
            "directory_outcomes": {},
        }


@dataclass(frozen=True)
class EvidenceRow:
    row: dict[str, Any]
    normalized: dict[str, Any]
    source_file: str
    direct_sidecar: bool
    media_references: tuple[str, ...]


@dataclass(frozen=True)
class DirectoryScanResult:
    relative_directory: str
    fields: dict[str, Any] | None
    outcome: str
    curated_csvs: tuple[str, ...] = ()
    media_count: int = 0
    candidate_count: int = 0
    error_code: str | None = None


def _join_relative(parent: str, child: str) -> str:
    return f"{parent}/{child}" if parent else child


def _under_scope(path: str, scope: str) -> bool:
    return not scope or path == scope or path.startswith(scope.rstrip("/") + "/")


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & _REPARSE_POINT)


def _safe_directory_files(
    root_key: str,
    relative_directory: str,
    *,
    nested_boundaries: Iterable[str] = (),
) -> list[str]:
    """Return safe original files under a work directory, without following links."""
    base = resolve_archive_path(root_key, relative_directory, must_exist=True)
    if not base.is_dir() or _is_reparse(base):
        raise DirectoryScanError("directory_unavailable", retryable=True)
    media: list[str] = []
    boundary_keys = {
        os.path.normcase(normalize_archive_relative_path(value).replace("/", os.sep))
        for value in nested_boundaries
        if value and value != relative_directory
    }
    stack = [(relative_directory, base, 0)]
    while stack:
        current_relative, current_path, depth = stack.pop()
        try:
            entries = sorted(os.scandir(current_path), key=lambda item: (item.name.casefold(), item.name))
        except (OSError, PermissionError):
            raise DirectoryScanError("directory_unreadable", retryable=True) from None
        for item in entries:
            if item.name.casefold() in _DERIVED_DIRS or item.name.startswith(".archive-") or item.name.endswith(".tmp"):
                continue
            relative = _join_relative(current_relative, item.name)
            key = os.path.normcase(relative.replace("/", os.sep))
            if any(key == boundary or key.startswith(boundary + os.sep) for boundary in boundary_keys):
                continue
            try:
                checked = resolve_archive_path(root_key, relative, must_exist=True)
            except (OSError, ValueError):
                # Symlink/reparse/out-of-root entries are deliberately ignored.
                continue
            if _is_reparse(checked):
                continue
            try:
                if item.is_dir(follow_symlinks=False) and checked.is_dir():
                    if depth >= _MAX_DEPTH:
                        continue
                    stack.append((relative, checked, depth + 1))
                    continue
                if not item.is_file(follow_symlinks=False) or not checked.is_file():
                    continue
                if checked.suffix.casefold() not in _MEDIA_EXTENSIONS or (
                    checked.name.casefold() in _DERIVED_FILES
                    and not (
                        current_relative != relative_directory
                        and checked.name.casefold() in {"cover.jpg", "cover.png"}
                    )
                ):
                    continue
                size = checked.stat().st_size
                if size > 0:
                    media.append(relative)
                    if len(media) > _MAX_MEDIA_PER_DIRECTORY:
                        raise DirectoryScanError("media_file_limit_exceeded")
            except OSError:
                continue
    return sorted(set(media), key=lambda value: (value.casefold(), value))


def build_scan_plan(
    root_key: str,
    relative_directory: str | None = None,
    *,
    work_directories: Iterable[str] = (),
    should_stop: Callable[[], bool] | None = None,
) -> ScanPlan:
    """Enumerate a bounded, deterministic set of media-bearing directories."""
    scope = normalize_archive_relative_path(relative_directory, allow_root=True) if relative_directory else ""
    start = resolve_archive_path(root_key, scope, allow_root=True, must_exist=True)
    if not start.is_dir():
        raise ScanPlanError("scan_target_not_directory")

    marker_keys = {
        physical_directory_key(normalize_archive_relative_path(item))
        for item in work_directories
        if item
    }
    directory_spellings = {physical_directory_key(scope): scope}
    visited = 0
    truncated = False
    unsafe_count = 0
    errors: list[dict[str, str]] = []
    evidence: set[str] = set()
    direct_media: dict[str, list[str]] = {}
    stack: list[tuple[str, Path, int]] = [(scope, start, 0)]

    while stack:
        if should_stop and should_stop():
            raise ScanPlanError("scan_interrupted")
        current_relative, current_path, depth = stack.pop()
        visited += 1
        if visited > _MAX_VISITED_DIRECTORIES:
            truncated = True
            break
        try:
            entries = sorted(os.scandir(current_path), key=lambda item: (item.name.casefold(), item.name))
        except (OSError, PermissionError):
            errors.append({"directory": current_relative, "code": "directory_unreadable"})
            continue

        for item in entries:
            name = item.name
            if name.startswith(".archive-") or name.endswith(".tmp"):
                continue
            child_relative = _join_relative(current_relative, name)
            try:
                checked = resolve_archive_path(root_key, child_relative, must_exist=True)
            except (OSError, ValueError):
                unsafe_count += 1
                continue
            if _is_reparse(checked):
                unsafe_count += 1
                continue
            try:
                if item.is_dir(follow_symlinks=False) and checked.is_dir():
                    if depth >= _MAX_DEPTH:
                        errors.append({"directory": child_relative, "code": "directory_depth_limit"})
                        truncated = True
                        continue
                    directory_spellings.setdefault(physical_directory_key(child_relative), child_relative)
                    stack.append((child_relative, checked, depth + 1))
                    continue
                if not item.is_file(follow_symlinks=False) or not checked.is_file():
                    continue
                if name in _EVIDENCE_FILES:
                    evidence.add(child_relative)
                    if len(evidence) > _MAX_EVIDENCE_FILES:
                        truncated = True
                        evidence.remove(child_relative)
                        continue
                if checked.suffix.casefold() in _MEDIA_EXTENSIONS and (
                    name.casefold() not in _DERIVED_FILES
                    or name.casefold() in {"cover.jpg", "cover.png"}
                ):
                    size = checked.stat().st_size
                    if size > 0:
                        direct_media.setdefault(current_relative, []).append(child_relative)
            except OSError:
                continue

    if unsafe_count:
        errors.append({"directory": scope, "code": "unsafe_paths_skipped"})

    # A physical work directory can keep images in a nested media folder. Treat
    # a directory with its own 作品信息 sidecar (or exact Work.media_path) as the
    # boundary and include descendants until a nested sidecar boundary begins.
    sidecar_markers = {
        path.rpartition("/")[0]
        for path in evidence
        if Path(path).name in {"作品信息.csv", "作品信息.json"}
    }
    marker_directories = {
        directory_spellings.get(key, key.replace("\\", "/"))
        for key in marker_keys
        if key in directory_spellings
    }
    marker_directories.update(sidecar_markers)
    for marker in marker_directories:
        if marker in direct_media:
            direct_media[marker] = [
                path for path in direct_media[marker]
                if Path(path).name.casefold() not in {"cover.jpg", "cover.png"}
            ]
            if not direct_media[marker]:
                direct_media.pop(marker)
    directory_set = set(direct_media)
    for marker in marker_directories:
        if not _under_scope(marker, scope):
            continue
        if any(path.startswith(marker.rstrip("/") + "/") for path in direct_media):
            directory_set.add(marker)

    # Marker directories define physical Work boundaries. Descendant media
    # folders belong to that entry, except a child that has its own marker.
    for child in list(directory_set):
        if child in marker_directories:
            continue
        if any(child.startswith(marker.rstrip("/") + "/") for marker in marker_directories if marker):
            directory_set.discard(child)

    directories = tuple(sorted(
        (item for item in directory_set if item and _under_scope(item, scope)),
        key=lambda value: (value.casefold(), value),
    ))
    root_level_count = len(direct_media.get("", []))
    unsupported = ("",) if root_level_count else ()
    if len(directories) > _MAX_VISITED_DIRECTORIES:
        directories = directories[:_MAX_VISITED_DIRECTORIES]
        truncated = True
    return ScanPlan(
        root_key=root_key,
        relative_directory=scope,
        directories=directories,
        evidence_files=tuple(sorted(evidence, key=lambda value: (value.casefold(), value))),
        unsupported_directories=unsupported,
        truncated=truncated,
        enumeration_errors=tuple(errors),
    )


def _decode_csv(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gb18030")


def _read_csv_rows(root_key: str, relative_path: str) -> list[dict[str, str]]:
    path = resolve_archive_path(root_key, relative_path, must_exist=True)
    if not path.is_file():
        return []
    try:
        if path.stat().st_size > _MAX_EVIDENCE_BYTES:
            raise DirectoryScanError("evidence_file_limit_exceeded")
        text = _decode_csv(path.read_bytes())
    except UnicodeDecodeError:
        raise DirectoryScanError("evidence_file_unreadable", retryable=True) from None
    except OSError:
        raise DirectoryScanError("evidence_file_unreadable", retryable=True) from None
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        rows = []
        for index, row in enumerate(reader):
            if index >= _MAX_ROWS_PER_EVIDENCE:
                break
            rows.append({str(key): value or "" for key, value in row.items() if key is not None})
        return rows
    except (csv.Error, UnicodeError):
        raise DirectoryScanError("evidence_file_malformed") from None


def _row_values(row: Mapping[str, Any], field: str) -> list[str]:
    values = []
    for name in LEGACY_COLUMN_ALIASES.get(field, ()):
        value = row.get(name)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def _row_references(
    root_key: str,
    row: Mapping[str, Any],
    *,
    source_file: str,
) -> tuple[str, ...]:
    row_root = row.get("root_key") or row.get("本地根目录标识")
    if row_root not in (None, "", root_key):
        return ()
    source_parent = source_file.rpartition("/")[0]
    refs: set[str] = set()
    raw_values = [*_row_values(row, "relative_directory"), *_row_values(row, "media_path")]
    for raw_value in raw_values:
        for raw in str(raw_value).splitlines():
            raw = raw.strip()
            if not raw:
                continue
            candidates: set[str] = set()
            if Path(raw).is_absolute() or PureWindowsPath(raw).drive or raw.startswith(("/", "\\")):
                try:
                    candidates.add(relative_path_from_root(root_key, raw))
                except (OSError, ValueError):
                    continue
            else:
                try:
                    candidates.add(normalize_archive_relative_path(raw))
                except ValueError:
                    continue
                if source_parent:
                    try:
                        candidates.add(normalize_archive_relative_path(f"{source_parent}/{raw}"))
                    except ValueError:
                        pass
            for candidate in candidates:
                try:
                    resolved = resolve_archive_path(root_key, candidate, must_exist=True)
                except (OSError, ValueError):
                    continue
                if resolved.is_dir():
                    refs.add(candidate)
                elif resolved.is_file():
                    refs.add(candidate)
                    parent = candidate.rpartition("/")[0]
                    if parent:
                        refs.add(parent)
    return tuple(sorted(refs, key=lambda value: (value.casefold(), value)))


def _row_matches_directory(row: Mapping[str, Any], references: Sequence[str], directory: str, media_files: Sequence[str]) -> bool:
    known = {directory, *media_files}
    for reference in references:
        if reference in known:
            return True
        if reference.startswith(directory.rstrip("/") + "/") and reference in media_files:
            return True
    return False


def _safe_sidecar_json(root_key: str, relative_path: str) -> list[dict[str, Any]]:
    path = resolve_archive_path(root_key, relative_path, must_exist=True)
    try:
        if path.stat().st_size > _MAX_EVIDENCE_BYTES:
            raise DirectoryScanError("evidence_file_limit_exceeded")
        document = json.loads(path.read_text(encoding="utf-8"))
    except DirectoryScanError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DirectoryScanError("evidence_file_unreadable", retryable=True) from None
    if not isinstance(document, Mapping):
        return []
    metadata = document.get("metadata") if isinstance(document.get("metadata"), Mapping) else {}
    row = dict(document)
    row["_archive_sidecar_main"] = True
    row.update({key: value for key, value in metadata.items() if key not in row})
    if isinstance(metadata.get("legacy_columns"), Mapping):
        row.update(metadata["legacy_columns"])
    output = [row]
    for candidate_row in metadata.get("legacy_rows", []) if isinstance(metadata.get("legacy_rows"), list) else []:
        if not isinstance(candidate_row, Mapping):
            continue
        candidate = dict(candidate_row)
        candidate["_archive_sidecar_main"] = False
        values = candidate.get("values")
        if isinstance(values, Mapping):
            candidate.update({key: value for key, value in values.items() if key not in candidate})
        candidate.setdefault("candidate_association", "legacy_json_candidate")
        output.append(candidate)
    return output


def _platform_from_url(value: Any) -> tuple[str | None, str | None, bool]:
    if not isinstance(value, str):
        return None, None, False
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
            return None, None, False
        if parsed.port not in (None, 80, 443):
            return None, None, False
    except ValueError:
        return None, None, False
    for platform, domains in _PLATFORM_HOSTS.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            pattern = _URL_ID_PATTERNS.get(platform)
            match = pattern.search(parsed.path) if pattern else None
            return platform, match.group(1) if match else None, True
    return None, None, False


def _safe_archive_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
            return None
        if parsed.port not in (None, 80, 443):
            return None
        host = (parsed.hostname or "").casefold().rstrip(".")
        if not any(host == domain or host.endswith("." + domain) for domains in _PLATFORM_HOSTS.values() for domain in domains):
            return None
        return parsed._replace(query="", fragment="").geturl()
    except ValueError:
        return None


def _valid_external_id(platform: str, external_id: str) -> bool:
    if platform == "bilibili":
        return bool(_BVID.fullmatch(external_id) or _AVID.fullmatch(external_id))
    if platform == "douyin":
        return bool(re.fullmatch(r"[0-9]{8,30}", external_id))
    if platform == "xhs":
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{6,128}", external_id))
    if platform == "twitter":
        return bool(re.fullmatch(r"[0-9]{5,25}", external_id))
    if platform == "wechat":
        return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", external_id))
    return False


def _infer_platform(
    *,
    external_id: str | None,
    url: str | None,
    directory: str,
    fallback: str | None = None,
) -> str | None:
    if external_id:
        if _BVID.fullmatch(external_id) or _AVID.fullmatch(external_id):
            return "bilibili"
        if re.fullmatch(r"[0-9]{8,30}", external_id):
            return "douyin"
        if re.fullmatch(r"[0-9]{5,25}", external_id):
            # A numeric ID is ambiguous without another source; do not infer X.
            pass
    url_platform, _url_id, recognized = _platform_from_url(url)
    if recognized:
        return url_platform
    text = directory.casefold()
    for code, label in ARCHIVE_PLATFORM_LABELS.items():
        tokens = {code.casefold(), label.casefold()}
        if code == "bilibili":
            tokens.update({"b站", "bili"})
        elif code == "twitter":
            tokens.update({"推特", "推特x"})
        elif code == "wechat":
            tokens.update({"微信", "公众号"})
        if any(token and token in text for token in tokens):
            return code
    return fallback if fallback in _KNOWN_PLATFORMS else None


def _same_identity(rows: Sequence[EvidenceRow]) -> tuple[set[tuple[str, str]], set[str]]:
    identities: set[tuple[str, str]] = set()
    platforms: set[str] = set()
    for evidence in rows:
        normalized = evidence.normalized
        platform = normalized.get("platform")
        external_id = normalized.get("external_id")
        if platform in _KNOWN_PLATFORMS:
            platforms.add(str(platform))
        if platform in _KNOWN_PLATFORMS and external_id not in (None, ""):
            value = str(external_id).strip()
            if _valid_external_id(str(platform), value):
                identities.add((str(platform), value))
    return identities, platforms


def _contains_identity_candidate_marker(rows: Sequence[EvidenceRow]) -> bool:
    for evidence in rows:
        for key, value in evidence.row.items():
            if not isinstance(value, str):
                continue
            combined = f"{key} {value}".casefold()
            if ("同名" in combined and "编号" in combined) or "按清单编号" in combined or "候选" in combined:
                return True
    return False


def _safe_legacy_row(row: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    safe, private = split_legacy_columns(row)
    for alias in LEGACY_COLUMN_ALIASES.get("url", ()):
        if alias in safe and safe[alias]:
            scrubbed = _safe_archive_url(safe[alias])
            safe[alias] = scrubbed or ""
    return _remove_sensitive_values(safe), private


def _remove_sensitive_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _remove_sensitive_values(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_remove_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return [_remove_sensitive_values(item) for item in value]
    return value


def _source_rows_for_directory(
    root_key: str,
    directory: str,
    media_files: Sequence[str],
    evidence_files: Sequence[str],
) -> tuple[list[EvidenceRow], tuple[str, ...]]:
    rows: list[EvidenceRow] = []
    curated: set[str] = set()
    for source_file in evidence_files:
        basename = Path(source_file).name
        direct_source = basename in {"作品信息.csv", "作品信息.json"} and source_file.rpartition("/")[0] == directory
        try:
            if basename == "作品信息.json":
                source_rows = _safe_sidecar_json(root_key, source_file) if direct_source else []
            elif basename.endswith(".csv"):
                source_rows = _read_csv_rows(root_key, source_file)
            else:
                source_rows = []
        except DirectoryScanError:
            if direct_source:
                raise
            continue
        for row in source_rows:
            direct = direct_source and (basename != "作品信息.json" or row.get("_archive_sidecar_main") is not False)
            references = _row_references(root_key, row, source_file=source_file)
            if direct or _row_matches_directory(row, references, directory, media_files):
                normalized = normalize_legacy_csv_row(
                    row,
                    root_key=root_key,
                    source_timezone="UTC" if basename == "作品信息.json" else "Asia/Shanghai",
                    source_name="archive_sidecar" if direct else "legacy_csv",
                )
                rows.append(EvidenceRow(
                    row=dict(row),
                    normalized=normalized,
                    source_file=source_file,
                    direct_sidecar=direct,
                    media_references=tuple(
                        reference for reference in references
                        if reference == directory or reference in media_files
                    ),
                ))
                if basename == "合集清单.csv":
                    curated.add(source_file)
    return rows, tuple(sorted(curated, key=lambda value: (value.casefold(), value)))


def _merge_candidate_rows(rows: Sequence[EvidenceRow]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for evidence in rows:
        safe_row, private_row = _safe_legacy_row(evidence.row)
        output.append({
            "source_file": evidence.source_file,
            "source_type": "archive_sidecar" if evidence.direct_sidecar else "legacy_csv",
            "association": "exact_media_path" if evidence.media_references else "directory_sidecar",
            "media_references": list(evidence.media_references),
            "values": safe_row,
            "private_values": private_row,
        })
    return output


def _candidate_by_file(rows: Sequence[EvidenceRow], media_files: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for evidence in rows:
        for media_path in evidence.media_references:
            if media_path not in media_files:
                continue
            normalized = evidence.normalized
            safe_url = _safe_archive_url(normalized.get("url"))
            candidate = {
                "source": "legacy_csv_candidate",
                "platform": normalized.get("platform"),
                "external_id": normalized.get("external_id"),
                "title": normalized.get("title"),
                "url": safe_url,
                "published_at": normalized.get("published_at"),
                "published_time_precision": normalized.get("published_time_precision"),
                "published_time_source": normalized.get("published_time_source"),
                "source_timezone": normalized.get("source_timezone"),
                "downloaded_at": normalized.get("downloaded_at"),
                "download_time_source": normalized.get("download_time_source"),
                "check_status": "needs_review",
                "source_file": evidence.source_file,
            }
            result.setdefault(media_path, []).append(candidate)
    for candidates in result.values():
        # Preserve the original per-media candidate rows while removing exact
        # duplicate evidence reached through a sidecar and a parent aggregate.
        seen = set()
        unique = []
        for candidate in candidates:
            key = json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        candidates[:] = unique
    return result


def _one_value(rows: Sequence[EvidenceRow], field: str) -> Any:
    values = []
    for evidence in rows:
        value = evidence.normalized.get(field)
        if value not in (None, "") and value not in values:
            values.append(value)
    return values[0] if len(values) == 1 else None


def _source_timezone_for_value(rows: Sequence[EvidenceRow], field: str, value: Any) -> str | None:
    timezones = {
        str(evidence.normalized.get("source_timezone"))
        for evidence in rows
        if evidence.normalized.get(field) == value
        and evidence.normalized.get("source_timezone") not in (None, "")
    }
    return next(iter(timezones)) if len(timezones) == 1 else None


def _entry_metadata(
    root_key: str,
    directory: str,
    media_files: Sequence[str],
    rows: Sequence[EvidenceRow],
    existing: ArchiveEntry | None,
    exact_path_work: Work | None,
) -> tuple[dict[str, Any] | None, str, int]:
    identities, row_platforms = _same_identity(rows)
    identity_conflict = len(identities) > 1
    platforms = set(row_platforms)
    if exact_path_work is not None:
        platforms.add(exact_path_work.platform)
    if len(platforms) > 1:
        return None, "unsupported", len(identities)

    identity = next(iter(identities)) if len(identities) == 1 and not identity_conflict else None
    platform = next(iter(platforms), None)
    external_id = identity[1] if identity and identity[0] == platform else None
    if external_id and identity and identity[0] != platform:
        identity_conflict = True
        external_id = None
    if exact_path_work is not None:
        path_identity = (exact_path_work.platform, exact_path_work.external_id)
        if identity and identity != path_identity:
            identity_conflict = True
            external_id = None
        elif not identity_conflict:
            platform, external_id = path_identity
    if not platform:
        platform = _infer_platform(
            external_id=external_id,
            url=_one_value(rows, "url"),
            directory=directory,
            fallback=existing.platform if existing else None,
        )
    if platform not in _KNOWN_PLATFORMS:
        return None, "unsupported", len(identities)

    if len(platforms) > 1 or (identity and identity[0] != platform):
        identity_conflict = True
    if identity_conflict:
        external_id = None
    if external_id and not _valid_external_id(platform, external_id):
        external_id = None

    work = None
    if not identity_conflict and exact_path_work is not None:
        if exact_path_work.platform == platform and (external_id is None or exact_path_work.external_id == external_id):
            work = exact_path_work
            external_id = external_id or exact_path_work.external_id
    if identity_conflict:
        work = None

    titles = []
    for evidence in rows:
        value = evidence.normalized.get("title")
        if isinstance(value, str) and value.strip() and value.strip() not in titles:
            titles.append(value.strip())
    title = titles[0] if len(titles) == 1 else (work.title if work and not titles else Path(directory).name)
    title_conflict = len(titles) > 1
    if not title:
        title = existing.title if existing else Path(directory).name
    if not title:
        return None, "unsupported", len(identities)

    urls = []
    url_conflict = False
    for evidence in rows:
        raw_url = evidence.normalized.get("url")
        safe_url = _safe_archive_url(raw_url)
        if not safe_url:
            continue
        url_platform, url_id, recognized = _platform_from_url(safe_url)
        if not recognized or url_platform != platform or (external_id and url_id and url_id != external_id):
            url_conflict = True
            continue
        if safe_url not in urls:
            urls.append(safe_url)
    url = urls[0] if len(urls) == 1 and not url_conflict else None

    ambiguous_marker = _contains_identity_candidate_marker(rows)
    canonical_rows = rows if not identity_conflict else ()
    published = _one_value(canonical_rows, "published_at")
    publication_source = _one_value(canonical_rows, "published_time_source")
    publication_precision = _one_value(canonical_rows, "published_time_precision")
    downloaded = _one_value(canonical_rows, "downloaded_at")
    download_source = _one_value(canonical_rows, "download_time_source")
    download_precision = _one_value(canonical_rows, "download_time_precision")
    metadata_checked = _one_value(canonical_rows, "metadata_checked_at")
    explicit_verified = bool(
        canonical_rows
        and all(item.normalized.get("check_status") == "verified" for item in canonical_rows)
        and (not titles or len(titles) == 1)
        and not title_conflict
        and not url_conflict
    )
    source_statuses = {item.normalized.get("check_status") for item in canonical_rows}
    if identity_conflict or url_conflict:
        check_status = "conflict"
    elif ambiguous_marker or title_conflict:
        check_status = "needs_review"
    elif explicit_verified and len(source_statuses) == 1:
        check_status = "verified"
    else:
        check_status = "needs_review"

    # Per-media database publication values predate source/precision tracking.
    # Keep them as candidates only; an ISO-shaped value is not proof of seconds.
    work_publication_candidate = None
    if work is not None and work.published_at and not getattr(work, "published_time_source", None):
        work_publication_candidate = {
            "value": work.published_at,
            "source": "local_work_db_candidate",
            "precision": None,
            "verified": False,
        }
    if work is not None and work.downloaded_at and work.download_time_source and not identity_conflict:
        downloaded = work.downloaded_at
        download_source = work.download_time_source
        download_precision = "second"
        download_timezone = "UTC"
    else:
        download_timezone = _source_timezone_for_value(canonical_rows, "downloaded_at", downloaded) if downloaded else None
    publication_timezone = _source_timezone_for_value(canonical_rows, "published_at", published) if published else None
    if published and not publication_timezone:
        # Several source-local interpretations cannot safely produce one
        # canonical time; the original per-file rows remain in candidate data.
        published = publication_source = publication_precision = metadata_checked = None
    if downloaded and not download_timezone:
        downloaded = download_source = download_precision = None

    creator = work.creator if work is not None else None
    group = work.group if work is not None else None
    creator_label = _one_value(canonical_rows, "creator_label") or (creator.name if creator else None)
    group_label = _one_value(canonical_rows, "group_label") or (group.name if group else None)
    creator_id = work.creator_id if work else None
    group_id = work.group_id if work else None

    matching_rows = [
        evidence for evidence in rows
        if evidence.direct_sidecar or evidence.media_references
    ]
    safe_rows = []
    private_rows = []
    for evidence in matching_rows:
        safe, private = _safe_legacy_row(evidence.row)
        safe_rows.append({
            "source_file": evidence.source_file,
            "source_type": "archive_sidecar" if evidence.direct_sidecar else "legacy_csv",
            "values": safe,
        })
        if private:
            private_rows.append({"source_file": evidence.source_file, "values": private})

    files_by_candidate = _candidate_by_file(rows, media_files)
    meta = dict(existing.metadata_json or {}) if existing else {}
    meta.update({
        "source_evidence": [
            {"source": "archive_sidecar" if item.direct_sidecar else "legacy_csv", "relative_path": item.source_file}
            for item in matching_rows
        ],
        "legacy_rows": safe_rows,
        "private_legacy_rows": private_rows,
        "legacy_candidates_by_file": files_by_candidate,
        "candidate_identity_count": len(identities),
        "identity_conflict": bool(identity_conflict),
    })
    if work_publication_candidate:
        meta["work_publication_candidate"] = work_publication_candidate
    if ambiguous_marker:
        meta["identity_review_required"] = True
        meta["identity_review_reason"] = "legacy same-title sequence association requires human review"
    if title_conflict:
        meta["title_candidates"] = titles

    legacy_columns: dict[str, Any] = {}
    # A single unambiguous source row can preserve custom columns on the
    # per-work sidecar. Per-media candidate rows remain only in legacy_rows.
    if not identity_conflict and len(matching_rows) == 1:
        safe, _private = _safe_legacy_row(matching_rows[0].row)
        legacy_columns = safe

    work_values = {
        "id": work.id if work else None,
        "platform": platform,
        "external_id": external_id,
        "title": title,
        "url": url,
        "creator_id": creator_id,
        "creator_label": creator_label,
        "group_id": group_id,
        "group_label": group_label,
        "published_at": published,
        "published_time_source": publication_source,
        "published_time_precision": publication_precision,
        "downloaded_at": downloaded,
        "download_time_source": download_source,
        "media_path": directory,
        "content_type": "video",
        "metadata_json": meta,
    }
    publication_provenance = None
    if published and publication_source:
        publication_provenance = {
            "value": published,
            "source": publication_source,
            "precision": publication_precision,
            "timezone": publication_timezone,
            "verified": explicit_verified,
            "check_status": check_status,
            "checked_at": metadata_checked,
        }
    download_provenance = None
    if downloaded and download_source:
        download_provenance = {
            "value": downloaded,
            "source": download_source,
            "precision": download_precision,
            "timezone": download_timezone,
            "verified": download_source == (work.download_time_source if work else None),
        }
    source_context = {
        "source_timezone": publication_timezone or download_timezone or "UTC",
        "published_timezone": publication_timezone or "UTC",
        "download_timezone": download_timezone or "UTC",
        "metadata_checked_at": metadata_checked,
        "check_status": check_status,
    }
    fields = build_archive_metadata(
        work_values,
        root_key,
        directory,
        media_files,
        existing=existing,
        publication_provenance=publication_provenance,
        download_provenance=download_provenance,
        source_context=source_context,
        legacy_columns=legacy_columns,
    )
    fields["metadata_json"].update(meta)
    if identity_conflict:
        fields.update({"work_id": None, "external_id": None, "url": None})
        fields["check_status"] = "conflict"
        if existing is None:
            fields.update({
                "published_at": None,
                "published_time_source": None,
                "published_time_precision": None,
                "downloaded_at": None,
                "download_time_source": None,
                "download_time_precision": None,
                "metadata_checked_at": None,
            })
    elif ambiguous_marker:
        fields["check_status"] = "needs_review"
        fields["metadata_json"]["identity_review_required"] = True
    elif check_status == "conflict":
        fields["check_status"] = "conflict"

    outcome = "conflict" if fields["check_status"] == "conflict" else (
        "unknown" if not external_id or not fields.get("published_at") else "indexed"
    )
    return fields, outcome, len(identities)


def _work_path_key(root_key: str, work: Work) -> str | None:
    if not work.media_path:
        return None
    raw = str(work.media_path)
    # The legacy Work.media_path contract is relative to MEDIA_ROOT. Only use a
    # relative path as exact evidence for that root; other roots need an
    # absolute path that resolves inside their allowlisted mapping.
    absolute = Path(raw).is_absolute() or bool(PureWindowsPath(raw).drive) or raw.startswith(("/", "\\"))
    if not absolute and root_key != "media":
        return None
    try:
        return relative_path_from_root(root_key, raw)
    except (ValueError, OSError):
        return None


def _apply_work_publication_evidence(fields: dict[str, Any], work: Work) -> None:
    """Promote only sourced Work timestamps; historical timestamp-only rows stay candidates."""
    value = getattr(work, "published_at", None)
    source = getattr(work, "published_time_source", None)
    precision = getattr(work, "published_time_precision", None)
    checked_at = getattr(work, "metadata_checked_at", None)
    source_timezone = (
        getattr(work, "published_time_timezone", None)
        or getattr(work, "publication_timezone", None)
    )
    if not value or not source or precision not in {"day", "minute", "second"} or not checked_at:
        return
    if precision in {"day", "minute"} and not source_timezone:
        fields.setdefault("metadata_json", {})["work_publication_candidate"] = {
            "value": value,
            "source": source,
            "precision": precision,
            "timezone": None,
            "verified": False,
        }
        return

    fields["published_at"] = str(value)
    fields["published_time_source"] = str(source)
    fields["published_time_precision"] = str(precision)
    fields["metadata_checked_at"] = str(checked_at)
    metadata = fields.setdefault("metadata_json", {})
    metadata["work_publication_evidence"] = {
        "value": value,
        "source": source,
        "precision": precision,
        "timezone": source_timezone or "UTC",
        "checked_at": checked_at,
        "verified": True,
    }
    provenance = metadata.setdefault("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
        metadata["provenance"] = provenance
    prior = provenance.get("published_at")
    provenance["published_at"] = {
        **(prior if isinstance(prior, Mapping) else {}),
        "source": source,
        "source_timezone": source_timezone or "UTC",
        "precision": precision,
        "verified": True,
        "checked_at": checked_at,
    }
    title_candidates = metadata.get("title_candidates")
    title_consistent = not title_candidates and str(fields.get("title") or "").strip() == str(work.title or "").strip()
    if (
        fields.get("check_status") != "conflict"
        and not metadata.get("identity_review_required")
        and title_consistent
    ):
        fields["check_status"] = "verified"


def _apply_explicit_clears(fields: dict[str, Any]) -> None:
    """Keep manual null corrections authoritative across later filesystem scans."""
    metadata = fields.get("metadata_json")
    if not isinstance(metadata, dict):
        return
    raw_cleared = metadata.get("explicit_cleared_fields")
    if not isinstance(raw_cleared, list):
        return
    cleared = {item for item in raw_cleared if isinstance(item, str)}
    if "external_id" in cleared:
        fields["external_id"] = None
        fields["work_id"] = None
        if fields.get("check_status") == "verified":
            fields["check_status"] = "needs_review"
    if "url" in cleared:
        fields["url"] = None
    if "creator_id" in cleared:
        fields["creator_id"] = None
    if "creator_label" in cleared:
        fields["creator_label"] = None
    if "group_id" in cleared:
        fields["group_id"] = None
    if "group_label" in cleared:
        fields["group_label"] = None
    if "published_at" in cleared:
        fields["published_at"] = None
        fields["published_time_source"] = None
        fields["published_time_precision"] = None
        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            provenance.pop("published_at", None)
    elif "published_time_precision" in cleared:
        fields["published_time_precision"] = None


def build_work_indexes(db: Session, root_key: str) -> tuple[dict[tuple[str, str], Work], dict[str, Work | None]]:
    """Build one batched exact-identity/path index for an entire scan job."""
    from sqlalchemy.orm import joinedload

    works = db.execute(
        select(Work).options(joinedload(Work.creator), joinedload(Work.group)).order_by(Work.id)
    ).unique().scalars().all()
    identities: dict[tuple[str, str], Work] = {}
    paths: dict[str, Work | None] = {}
    for work in works:
        identities[(work.platform, work.external_id)] = work
        directory = _work_path_key(root_key, work)
        if directory:
            physical_key = physical_directory_key(directory)
            if physical_key not in paths:
                paths[physical_key] = work
            elif paths[physical_key] is not None and (
                paths[physical_key].platform != work.platform
                or paths[physical_key].external_id != work.external_id
            ):
                # Multiple Works pointing at one physical path cannot choose
                # an identity from path evidence alone.
                paths[physical_key] = None
    return identities, paths


def work_directories_for_root(work_paths: Mapping[str, Work | None]) -> tuple[str, ...]:
    return tuple(sorted(work_paths, key=lambda value: (value.casefold(), value)))


def scan_directory(
    root_key: str,
    relative_directory: str,
    evidence_files: Sequence[str],
    *,
    existing: ArchiveEntry | None,
    work_by_identity: Mapping[tuple[str, str], Work],
    work_by_path: Mapping[str, Work | None],
) -> DirectoryScanResult:
    """Read one physical directory and return an upsert payload, without DB writes."""
    directory = normalize_archive_relative_path(relative_directory)
    directory_key = physical_directory_key(directory).rstrip("\\/")
    nested_boundaries = {
        marker for marker in work_by_path
        if marker.startswith(directory_key + os.sep)
    }
    nested_boundaries.update(
        path.rpartition("/")[0]
        for path in evidence_files
        if Path(path).name in {"作品信息.csv", "作品信息.json"}
        and path.rpartition("/")[0].startswith(directory.rstrip("/") + "/")
    )
    media_files = _safe_directory_files(root_key, directory, nested_boundaries=nested_boundaries)
    if not media_files:
        return DirectoryScanResult(directory, None, "unknown", error_code="media_directory_empty")
    rows, curated_csvs = _source_rows_for_directory(root_key, directory, media_files, evidence_files)
    fields, outcome, candidate_count = _entry_metadata(
        root_key,
        directory,
        media_files,
        rows,
        existing,
        work_by_path.get(physical_directory_key(directory)),
    )
    if fields is not None:
        external_id = fields.get("external_id")
        platform = fields.get("platform")
        if external_id and platform:
            exact_work = work_by_identity.get((platform, external_id))
            if exact_work is not None:
                fields["work_id"] = exact_work.id
                fields["creator_id"] = exact_work.creator_id
                fields["creator_label"] = exact_work.creator.name if exact_work.creator else fields.get("creator_label")
                fields["group_id"] = exact_work.group_id
                fields["group_label"] = exact_work.group.name if exact_work.group else fields.get("group_label")
                # Historical Work rows with timestamp-only values have no
                # source/precision proof; retain them as candidates.
                if exact_work.published_at and not getattr(exact_work, "published_time_source", None):
                    fields["metadata_json"]["work_publication_candidate"] = {
                        "value": exact_work.published_at,
                        "source": "local_work_db_candidate",
                        "precision": None,
                        "verified": False,
                    }
                if exact_work.downloaded_at and exact_work.download_time_source:
                    fields["downloaded_at"] = exact_work.downloaded_at
                    fields["download_time_source"] = exact_work.download_time_source
                    fields["download_time_precision"] = "second"
        if fields.get("metadata_json", {}).get("identity_review_required"):
            fields["check_status"] = "needs_review"
        if fields.get("external_id") and fields.get("platform"):
            identity_work = work_by_identity.get((fields["platform"], fields["external_id"]))
            if identity_work is not None:
                _apply_work_publication_evidence(fields, identity_work)
        _apply_explicit_clears(fields)
        outcome = "conflict" if fields.get("check_status") == "conflict" else (
            "unknown" if not fields.get("external_id") or not fields.get("published_at") else "indexed"
        )
    return DirectoryScanResult(
        relative_directory=directory,
        fields=fields,
        outcome=outcome,
        curated_csvs=curated_csvs,
        media_count=len(media_files),
        candidate_count=candidate_count,
        error_code="unsupported_platform" if fields is None else None,
    )


def read_scan_plan(root_key: str, cursor: Mapping[str, Any]) -> ScanPlan:
    """Rehydrate only the persisted root-relative plan fields after a restart."""
    directories = cursor.get("directories")
    evidence_files = cursor.get("evidence_files")
    if not isinstance(directories, list) or not isinstance(evidence_files, list):
        raise ScanPlanError("scan_cursor_invalid")
    safe_directories = tuple(normalize_archive_relative_path(item) for item in directories if isinstance(item, str))
    safe_evidence = tuple(normalize_archive_relative_path(item) for item in evidence_files if isinstance(item, str))
    return ScanPlan(
        root_key=root_key,
        relative_directory=normalize_archive_relative_path(str(cursor.get("relative_directory") or ""), allow_root=True),
        directories=safe_directories,
        evidence_files=safe_evidence,
        unsupported_directories=tuple(item for item in cursor.get("unsupported_directories", []) if isinstance(item, str)),
        truncated=bool(cursor.get("truncated")),
        enumeration_errors=tuple(item for item in cursor.get("enumeration_errors", []) if isinstance(item, Mapping)),
    )


def safe_scan_error(exc: BaseException) -> str:
    """Turn OS/SQL/path failures into a stable path-free worker message."""
    if isinstance(exc, DirectoryScanError):
        return exc.code
    if isinstance(exc, ScanPlanError):
        return str(exc)
    return f"archive_scan_failed:{type(exc).__name__}"


def safe_metadata_projection(metadata: Any) -> dict[str, Any]:
    """Return path/secret-safe metadata for ArchiveEntry DTOs."""
    from app.services.archive_metadata_service import public_archive_metadata

    return _remove_sensitive_values(public_archive_metadata(metadata))


def canonical_file_id(root_key: str, relative_path: str) -> str:
    import hashlib

    normalized = normalize_archive_relative_path(relative_path)
    return "f_" + hashlib.sha256(f"{root_key}\0{normalized}".encode("utf-8")).hexdigest()[:32]


def refresh_curated_csv(
    root_key: str,
    relative_path: str,
    archive_entry_id: int,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Update only exact selected rows in one existing curated collection CSV.

    The Task2 sync module owns the shared root lock and atomic replacement; the
    public CSV refresher preserves row count, membership, and user columns.
    """
    from app.core.db import SessionLocal
    from app.repositories.archive_repo import export_entries
    from app.services.archive_sync_service import _atomic_replace, _root_lock, refresh_legacy_csv

    normalized = normalize_archive_relative_path(relative_path)
    if Path(normalized).name != "合集清单.csv":
        return False
    target = resolve_archive_path(root_key, normalized, must_exist=True)
    if not target.is_file():
        return False
    factory = session_factory or SessionLocal
    with _root_lock(root_key):
        # The canonical snapshot and selected file rows are loaded only after
        # the same cross-process lock used by Task2's sync implementation.
        target = resolve_archive_path(root_key, normalized, must_exist=True)
        with factory() as db:
            entries = export_entries(db, filters={"root_key": root_key})
            if not any(item.id == archive_entry_id for item in entries):
                return False
            content = target.read_bytes()
            refreshed = refresh_legacy_csv(content, entries, root_key, per_media=True)
        _atomic_replace(root_key, normalized, refreshed)
    return True
