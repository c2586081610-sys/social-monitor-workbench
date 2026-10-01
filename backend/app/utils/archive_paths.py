"""Allowlisted archive path resolution and stable work-directory naming."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from pathlib import Path, PureWindowsPath

from app.core.config import ARCHIVE_PLATFORM_LABELS, settings
from app.utils.filename import sanitize_filename


_REPARSE_POINT = 0x0400
_WINDOWS_PATH_BUDGET = 240
_MAX_COMPONENT_LENGTH = 180
_PRECISION_LABELS = {"day", "minute", "second"}
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"COM{i}" for i in range(1, 10)
} | {f"LPT{i}" for i in range(1, 10)} | {"COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}


def _safe_component(value: str, max_len: int) -> str:
    clean = sanitize_filename(str(value), max_len=max_len)
    clean = "".join(
        "_" if unicodedata.category(char) == "Cc" else char for char in clean
    ).rstrip(" .")
    if not clean:
        clean = "untitled"
    if clean.split(".", 1)[0].rstrip(" .").upper() in _WINDOWS_RESERVED:
        clean = "_" + clean
    return clean


def _path_units(value: str) -> int:
    """Count Windows path length in UTF-16 code units, not Python code points."""
    return len(value.encode("utf-16-le")) // 2


def _truncate_path_units(value: str, max_units: int) -> str:
    output = []
    used = 0
    for char in value:
        units = 2 if ord(char) > 0xFFFF else 1
        if used + units > max_units:
            break
        output.append(char)
        used += units
    return "".join(output).rstrip(" .")


def _root(root_key: str) -> Path:
    if not isinstance(root_key, str) or root_key not in settings.archive_root_paths:
        raise ValueError("Unknown archive root key")
    root = Path(settings.archive_root_paths[root_key])
    try:
        _reject_reparse_chain(root)
        canonical = root.resolve(strict=False)
        if root.exists() and not root.is_dir():
            raise ValueError("Configured archive root is not a directory")
    except OSError as exc:
        raise ValueError("Configured archive root is unavailable") from exc
    return canonical


def _reject_reparse(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError("Archive path cannot be inspected safely") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    if stat.S_ISLNK(info.st_mode) or attrs & _REPARSE_POINT:
        raise ValueError("Archive paths must not traverse links or reparse points")


def _reject_reparse_chain(path: Path) -> None:
    """Inspect each existing configured-root ancestor before resolving aliases."""
    absolute = path.absolute()
    chain = [*reversed(absolute.parents), absolute]
    for item in chain:
        _reject_reparse(item)


def _validate_segment(part: str, *, allow_drive: bool = False) -> None:
    if part in {"", "."}:
        return
    if part == ".." or part.rstrip(" .") == "..":
        raise ValueError("Archive paths must not contain parent traversal")
    if allow_drive and re.fullmatch(r"[A-Za-z]:", part):
        return
    if ":" in part:
        raise ValueError("Drive and alternate-stream syntax is not accepted")
    if part.endswith((".", " ")) or any(
        unicodedata.category(char) == "Cc" or char in '<>"|?*' for char in part
    ):
        raise ValueError("Archive path contains a Windows-invalid segment")
    device_stem = part.split(".", 1)[0].rstrip(" .").upper()
    if device_stem in _WINDOWS_RESERVED:
        raise ValueError("Archive path contains a reserved Windows device name")


def _validate_raw_stored_path(raw: str) -> None:
    """Reject path aliases before Path.absolute() can collapse dot segments."""
    parts = raw.replace("\\", "/").split("/")
    drive = PureWindowsPath(raw).drive
    first = next((index for index, part in enumerate(parts) if part), None)
    for index, part in enumerate(parts):
        _validate_segment(part, allow_drive=(index == first and part == drive))


def normalize_archive_relative_path(relative_path: str, *, allow_root: bool = False) -> str:
    """Return a portable slash path and reject absolute, drive, ADS, and parent paths."""
    if not isinstance(relative_path, str) or "\x00" in relative_path:
        raise ValueError("Archive path must be a relative path")
    raw = relative_path.replace("\\", "/")
    if not raw or raw in {".", "./"}:
        if allow_root:
            return ""
        raise ValueError("Archive path must identify an item below the root")
    win = PureWindowsPath(relative_path)
    if raw.startswith("/") or win.drive or win.is_absolute():
        raise ValueError("Absolute archive paths are not accepted")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        _validate_segment(part)
        parts.append(part)
    if not parts:
        if allow_root:
            return ""
        raise ValueError("Archive path must identify an item below the root")
    return "/".join(parts)


def resolve_archive_path(
    root_key: str,
    relative_path: str,
    *,
    allow_root: bool = False,
    must_exist: bool = False,
) -> Path:
    """Resolve one server-root-relative path and reject every link/reparse hop.

    Absolute paths are never accepted here, including paths that happen to point
    back inside an allowlisted root. Callers that have a trusted persisted path
    must first convert it to a root-relative value.
    """
    root = _root(root_key)
    relative = normalize_archive_relative_path(relative_path, allow_root=allow_root)
    candidate = root
    for part in relative.split("/") if relative else ():
        candidate = candidate / part
        _reject_reparse(candidate)
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("Archive path leaves its configured root") from exc
    if must_exist and not resolved.exists():
        raise FileNotFoundError("Archive path does not exist")
    return resolved


def relative_path_from_root(root_key: str, stored_path: str) -> str:
    """Safely normalize a persisted Work media path to its allowlisted root."""
    if not isinstance(stored_path, str) or not stored_path.strip():
        raise ValueError("Stored media path is empty")
    root = _root(root_key)
    raw = stored_path
    _validate_raw_stored_path(raw)
    candidate = Path(raw)
    if candidate.is_absolute() or PureWindowsPath(raw).drive or raw.startswith(("\\", "/")):
        try:
            lexical = candidate.absolute()
            rel = lexical.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("Stored media path is outside its configured root") from exc
        relative = rel.as_posix()
    else:
        relative = normalize_archive_relative_path(raw)
        # Work.media_path is already stored relative to its selected root. Keep
        # that spelling exactly; stripping a folder named `media` or `fitness`
        # could silently redirect an existing archive to a different directory.
    normalized = normalize_archive_relative_path(relative)
    resolve_archive_path(root_key, normalized)
    return normalized


def _value(record, key: str, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def make_archive_parent_relative(work) -> str:
    """Return a portable ``group/creator`` parent for a new archive directory."""
    external_id = _value(work, "external_id") or _value(work, "id") or "未知博主"
    creator = _value(work, "creator")
    group = _value(work, "group")
    creator_name = _value(creator, "name") if creator is not None else None
    group_name = _value(group, "name") if group is not None else None
    return "/".join((
        _safe_component(str(group_name or "未分组"), max_len=80),
        _safe_component(str(creator_name or external_id), max_len=80),
    ))


def _directory_time(work, publication_provenance: dict | None) -> str:
    provenance = publication_provenance or {}
    verified = provenance.get("verified") is True or provenance.get("check_status") == "verified"
    source = provenance.get("source")
    value = provenance.get("value", provenance.get("published_at"))
    precision = provenance.get("precision", provenance.get("published_time_precision"))
    if not verified or not source or not value or precision not in _PRECISION_LABELS:
        return "发布时间未知"

    from datetime import datetime
    from zoneinfo import ZoneInfo

    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "发布时间未知"
    timezone_name = str(provenance.get("timezone") or "UTC")
    try:
        source_zone = ZoneInfo(timezone_name)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=source_zone)
    except Exception:
        return "发布时间未知"
    local = parsed.astimezone(ZoneInfo("Asia/Shanghai"))
    if precision == "day":
        # A day-only source has no instant to convert. Keep its source-local day.
        return parsed.astimezone(source_zone).strftime("%Y-%m-%d")
    if precision == "minute":
        return local.strftime("%Y-%m-%d_%H-%M")
    return local.strftime("%Y-%m-%d_%H-%M-%S")


def make_work_directory_name(
    work,
    root_key: str,
    parent_relative_directory: str = "",
    *,
    publication_provenance: dict | None = None,
) -> str:
    """Build a safe, precision-aware directory component while retaining a stable ID.

    `publication_provenance` must explicitly mark a verified value and precision;
    an ISO-looking Work.published_at alone is not treated as verified metadata.
    """
    root = _root(root_key)
    parent = normalize_archive_relative_path(parent_relative_directory, allow_root=True)
    title = str(_value(work, "title") or "untitled")
    platform = str(_value(work, "platform") or "unknown")
    platform_label = ARCHIVE_PLATFORM_LABELS.get(platform, platform)
    external_id = _value(work, "external_id") or _value(work, "id")
    if external_id is None or not str(external_id).strip():
        raise ValueError("A stable external ID is required for a new work directory")

    raw_id = str(external_id)
    clean_id = _safe_component(raw_id, max_len=100)
    if clean_id != raw_id or len(clean_id) > 100:
        clean_id = f"{_safe_component(raw_id, max_len=64)}-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:16]}"
    date_label = _directory_time(work, publication_provenance)
    prefix = f"{date_label}_{_safe_component(platform_label, max_len=30)}_"
    suffix = f"_{clean_id}"

    # Budget the complete Windows path conservatively, even on Unix hosts. The
    # title is the only elastic part; if the ID alone is too long, retain a
    # stable digest representation instead of truncating it away.
    root_text = str(root)
    parent_text = parent.replace("/", "\\") if parent else ""
    full_parent_length = _path_units(root_text) + (1 + _path_units(parent_text) if parent_text else 0)
    component_budget = min(_MAX_COMPONENT_LENGTH, _WINDOWS_PATH_BUDGET - full_parent_length - 1)
    if component_budget < 1:
        raise ValueError("Parent directory leaves no safe Windows path budget for a work name")
    if _path_units(prefix) + _path_units(suffix) + 1 > component_budget:
        if clean_id == raw_id and _path_units(raw_id) <= 64:
            raise ValueError("Parent directory leaves no safe path budget for the stable work ID")
        digest_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]
        suffix = f"_id-{digest_id}"
        if _path_units(prefix) + _path_units(suffix) + 1 > component_budget:
            raise ValueError("Parent directory leaves no safe path budget for the stable work ID")
    title_budget = min(120, component_budget - _path_units(prefix) - _path_units(suffix))
    safe_title = _safe_component(title, max_len=max(1, title_budget))
    if _path_units(safe_title) > title_budget:
        safe_title = _truncate_path_units(safe_title, title_budget) or "_"
    component = f"{prefix}{safe_title}{suffix}"
    if _path_units(component) > component_budget:
        raise ValueError("Generated archive directory exceeds its path budget")
    if component.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        component = f"_{component}"
    return component.rstrip(" .") or "untitled"
