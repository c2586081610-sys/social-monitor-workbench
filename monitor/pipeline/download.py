"""Platform download adapters with validated, backward-compatible receipts.

``download()`` keeps the original ``-> str`` contract. Archive-aware callers
should use ``download_with_result()`` and pass only media records already
registered for that work. A directory scan alone never makes an old file a
successful download receipt.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .download_result import DownloadResult, MediaFile

logger = logging.getLogger("monitor.pipeline.download")

_COOKIE_CONFIG = os.getenv("PLATFORM_COOKIES_FILE", "")
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".flv", ".webm", ".m4v", ".avi", ".ts"}
_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".opus"}
_DERIVED_DIRS = {"frames", "images", "transcript", "transcripts", "notes", "transcription"}
_REPARSE_POINT = 0x0400


class PipelineOfflineError(Exception):
    """A downloader is unavailable, failed, or produced no verifiable new media."""


@dataclass(frozen=True)
class _FileObservation:
    size_bytes: int
    mtime_ns: int
    ctime_ns: int
    inode: int


def _project_root() -> Path:
    # download.py is <project>/monitor/pipeline/download.py; parents[2] is
    # the project root. Going one parent farther would leave the project root.
    return Path(__file__).resolve().parents[2]


def _python_executable() -> str:
    """Use the configured helper interpreter when available, else this Python."""
    configured = os.getenv("PYTHON_EXE", "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        logger.warning("PYTHON_EXE is unavailable; using the current interpreter")
    return sys.executable


def _load_platform_cookies() -> dict[str, Any]:
    """Load optional platform cookies without logging paths or credential data."""
    path = Path(_COOKIE_CONFIG).expanduser() if _COOKIE_CONFIG else _project_root() / "config" / "platform_cookies.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("platform cookie configuration could not be read")
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_cli(platform: str, command: list[str], *, cwd: str | Path | None = None) -> None:
    """Run a downloader silently; never echo URLs, cookies, auth paths, or argv."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        raise PipelineOfflineError(f"{platform} downloader could not start") from None
    if completed.returncode != 0:
        raise PipelineOfflineError(f"{platform} downloader failed (exit code {completed.returncode})")


def _is_reparse(info) -> bool:
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & _REPARSE_POINT)


def _safe_file_under(media_dir: Path, path: Path) -> Path:
    """Resolve an original file below media_dir without following links."""
    base = media_dir.absolute()
    candidate = path if path.is_absolute() else base / path
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("media receipt path leaves its work directory") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("media receipt path is not a file below its work directory")

    current = base
    try:
        base_info = current.lstat()
    except OSError as exc:
        raise ValueError("media work directory cannot be inspected") from exc
    if _is_reparse(base_info):
        raise ValueError("media work directory cannot be a link")
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise ValueError("media receipt file is unavailable") from exc
        if _is_reparse(info):
            raise ValueError("media receipt cannot traverse links")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("media receipt path contains a non-directory component")
        if index == len(relative.parts) - 1 and not stat.S_ISREG(info.st_mode):
            raise ValueError("media receipt is not a regular file")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(base.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("media receipt path leaves its work directory") from exc
    return resolved


def _coerce_registered(item: Any) -> tuple[Path, int, str | None, str | None]:
    """Read an explicit persisted file record; a bare path is not registration."""
    if isinstance(item, MediaFile):
        return item.path, item.size_bytes, item.media_type, item.sha256
    if isinstance(item, Mapping):
        raw_path = item.get("path", item.get("relative_path"))
        size = item.get("size_bytes")
        if raw_path is None or isinstance(size, bool) or not isinstance(size, int):
            raise ValueError("registered media requires a path and validated size")
        media_type = item.get("media_type")
        digest = item.get("sha256")
        if media_type is not None and not isinstance(media_type, str):
            raise ValueError("registered media type must be a string")
        if digest is not None and not isinstance(digest, str):
            raise ValueError("registered media hash must be a string")
        return Path(str(raw_path)), size, media_type, digest
    raise ValueError("registered media must include its persisted file record")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in _VIDEO_EXTENSIONS:
        return "video"
    if suffix in _AUDIO_EXTENSIONS:
        return "audio"
    return None


def _is_derived_registered_path(path: Path) -> bool:
    return any(part.casefold() in _DERIVED_DIRS for part in path.parts[:-1])


def _registered_media_files(
    media_dir: Path,
    registered_files: Iterable[Any],
) -> tuple[tuple[MediaFile, ...], bool]:
    """Return verified originals and whether every eligible registration was valid."""
    valid: dict[Path, MediaFile] = {}
    complete = True
    for item in registered_files or ():
        raw_path_value = item.path if isinstance(item, MediaFile) else (
            item.get("path", item.get("relative_path")) if isinstance(item, Mapping) else None
        )
        if raw_path_value is None:
            complete = False
            continue
        try:
            path_hint = Path(raw_path_value)
        except (TypeError, ValueError):
            complete = False
            continue
        if _is_derived_registered_path(path_hint):
            continue
        if _media_type(path_hint) is None:
            continue
        try:
            raw_path, expected_size, declared_type, expected_hash = _coerce_registered(item)
        except (TypeError, ValueError):
            complete = False
            continue
        inferred_type = _media_type(raw_path)
        if inferred_type is None:
            continue
        if declared_type not in {None, inferred_type}:
            complete = False
            continue
        try:
            resolved = _safe_file_under(media_dir, raw_path)
            info = resolved.stat()
            if expected_size <= 0 or info.st_size <= 0 or info.st_size != expected_size:
                complete = False
                continue
            digest = _sha256(resolved) if expected_hash else None
            if expected_hash and digest.lower() != expected_hash.lower():
                complete = False
                continue
            # Recheck the size after hashing to avoid accepting a concurrent edit.
            if resolved.stat().st_size != info.st_size:
                complete = False
                continue
        except (OSError, ValueError):
            complete = False
            continue
        valid[resolved] = MediaFile(resolved, info.st_size, inferred_type, digest or expected_hash)
    files = tuple(valid[path] for path in sorted(valid, key=lambda value: str(value).casefold()))
    return files, complete


def _observe(path: Path) -> _FileObservation | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    if _is_reparse(info) or not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        return None
    return _FileObservation(info.st_size, info.st_mtime_ns, info.st_ctime_ns, getattr(info, "st_ino", 0))


def _original_media_paths(media_dir: Path) -> list[Path]:
    """Find only original audio/video candidates, excluding known derived folders."""
    found: list[Path] = []
    try:
        candidates = media_dir.rglob("*")
        for path in candidates:
            try:
                relative = path.relative_to(media_dir)
                if any(part.casefold() in _DERIVED_DIRS for part in relative.parts[:-1]):
                    continue
                if path.suffix.lower() not in _VIDEO_EXTENSIONS | _AUDIO_EXTENSIONS:
                    continue
                if _observe(path) is not None:
                    _safe_file_under(media_dir, path)
                    found.append(path.resolve(strict=True))
            except (OSError, ValueError):
                continue
    except OSError:
        return []
    return sorted(set(found), key=lambda value: str(value).casefold())


def _snapshot(media_dir: Path) -> dict[Path, _FileObservation]:
    return {
        path: observation
        for path in _original_media_paths(media_dir)
        if (observation := _observe(path)) is not None
    }


def _new_media_files(media_dir: Path, before: Mapping[Path, _FileObservation]) -> tuple[MediaFile, ...]:
    new_files: list[MediaFile] = []
    for path in _original_media_paths(media_dir):
        after = _observe(path)
        if after is None:
            continue
        previous = before.get(path)
        if previous is not None and previous == after:
            continue
        try:
            safe_path = _safe_file_under(media_dir, path)
            before_hash_stat = safe_path.stat()
            digest = _sha256(safe_path)
            after_hash_stat = safe_path.stat()
        except (OSError, ValueError):
            continue
        if (
            before_hash_stat.st_size <= 0
            or before_hash_stat.st_size != after_hash_stat.st_size
            or before_hash_stat.st_mtime_ns != after_hash_stat.st_mtime_ns
        ):
            continue
        new_files.append(MediaFile(safe_path, after_hash_stat.st_size, _media_type(safe_path), digest))
    return tuple(new_files)


def _completed_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# 抖音 jiji262 画质档位。480p 是本项目实测的最低含音轨档。
_JIJI_VIDEO_QUALITY = "480p"
_JIJI_QUALITY_NOTE = "# 480p 为本项目最低可转写档位\n"


def _ensure_jiji_config(cfg: Path) -> None:
    """Generate/upgrade the jiji config without logging a machine-specific path."""
    if not cfg.exists():
        cfg.write_text(
            _JIJI_QUALITY_NOTE
            + f"video_quality: {_JIJI_VIDEO_QUALITY}\n"
            + "thread: 3\nretry_times: 3\nprogress:\n  quiet_logs: true\n",
            encoding="utf-8",
        )
        logger.info("created jiji downloader configuration at the default quality")
        return
    text = cfg.read_text(encoding="utf-8")
    if re.search(r"^video_quality:\s*lowest\s*$", text, re.M):
        text = re.sub(r"^video_quality:\s*lowest\s*$", f"video_quality: {_JIJI_VIDEO_QUALITY}", text, flags=re.M)
        cfg.write_text(text, encoding="utf-8")
    elif "video_quality:" not in text:
        cfg.write_text(_JIJI_QUALITY_NOTE + f"video_quality: {_JIJI_VIDEO_QUALITY}\n" + text, encoding="utf-8")


MEDIACRAWLER_PLATFORMS = {"xhs", "douyin", "bilibili", "weibo", "tieba", "zhihu", "kuaishou"}


def download_via_mediacrawler(platform: str, target: str, out_dir: Path) -> str:
    """Run the existing MediaCrawler fallback without echoing the target URL."""
    mc_dir_value = os.getenv("MEDIACRAWLER_DIR", "")
    if not mc_dir_value:
        raise PipelineOfflineError("MediaCrawler is not configured")
    mc_dir = Path(mc_dir_value)
    if not (mc_dir / "main.py").is_file():
        raise PipelineOfflineError("MediaCrawler directory is unavailable")
    command = ["uv", "run", "main.py", "--platform", platform, "--lt", "qrcode", "--type", "detail"]
    _run_cli(platform, command, cwd=mc_dir)
    # The legacy fallback contract returns its output directory for downstream handling.
    return str(out_dir)


def _invoke_downloader(platform: str, url: str, media_dir: Path) -> None:
    if platform == "douyin":
        jiji_dir_value = os.getenv("DOUYIN_DOWNLOADER_DIR", "")
        if not jiji_dir_value:
            raise PipelineOfflineError("Douyin downloader is not configured")
        jiji_dir = Path(jiji_dir_value)
        cfg = jiji_dir / "config.yml"
        try:
            _ensure_jiji_config(cfg)
        except OSError:
            raise PipelineOfflineError("Douyin downloader configuration is unavailable") from None
        _run_cli(
            platform,
            [_python_executable(), "run.py", "-c", str(cfg), "-u", url, "-p", str(media_dir)],
            cwd=jiji_dir,
        )
        return

    if platform == "bilibili":
        try:
            import yutto  # noqa: F401
        except ImportError as exc:
            raise PipelineOfflineError("yutto is not installed") from exc
        command = [sys.executable, "-m", "yutto", "download", url, "-d", str(media_dir), "-q", "16"]
        configured_auth = os.getenv("BILIBILI_AUTH_FILE", "").strip()
        auth_file = Path(configured_auth).expanduser() if configured_auth else _project_root() / "config" / "yutto_auth.toml"
        skip_auth = os.getenv("BILIBILI_SKIP_AUTH", "").strip().casefold() in {"1", "true", "yes", "on"}
        if auth_file.is_file() and not skip_auth:
            command += ["--auth-file", str(auth_file)]
        skip_danmaku = os.getenv("BILIBILI_SKIP_DANMAKU", "").strip().casefold() in {"1", "true", "yes", "on"}
        if skip_danmaku:
            command += ["--no-danmaku"]
        _run_cli(platform, command)
        return

    if platform == "xhs":
        xhs_dir = _project_root() / "tools" / "xhs-downloader"
        script = xhs_dir / "main.py"
        if not script.is_file():
            raise PipelineOfflineError("XHS downloader is not configured")
        cookie_section = _load_platform_cookies().get("xhs", {})
        cookie_string = cookie_section.get("cookie", "") if isinstance(cookie_section, dict) else ""
        if not isinstance(cookie_string, str) or not cookie_string:
            raise PipelineOfflineError("XHS download requires a configured browser cookie")
        _run_cli(
            platform,
            [
                sys.executable,
                str(script),
                "--url", url,
                "--work_path", str(media_dir),
                "--folder_mode", "False",
                "--cookie", cookie_string,
            ],
            cwd=xhs_dir,
        )
        return

    if platform == "twitter":
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise PipelineOfflineError("yt-dlp is not installed") from exc
        cookie_section = _load_platform_cookies().get("twitter", {})
        cookies_file = cookie_section.get("cookies_file", "") if isinstance(cookie_section, dict) else ""
        proxy = os.getenv("TWITTER_PROXY", "http://127.0.0.1:7892")
        command = [sys.executable, "-m", "yt_dlp", "-f", "worst", url]
        if cookies_file:
            command += ["--cookies", str(cookies_file)]
        else:
            logger.warning("Twitter cookies are not configured")
        command += ["--proxy", proxy, "-o", str(media_dir / "%(title)s.%(ext)s")]
        _run_cli(platform, command)
        return

    if platform in MEDIACRAWLER_PLATFORMS:
        download_via_mediacrawler(platform, url, media_dir)
        return
    raise PipelineOfflineError(f"unsupported downloader platform: {platform}")


def download_with_result(
    platform: str,
    url: str,
    media_dir: Path,
    *,
    registered_files: Iterable[MediaFile | Mapping[str, Any]] = (),
) -> DownloadResult:
    """Download video/audio and return only verified new or registered original media.

    ``registered_files`` accepts the shared ``MediaFile`` type or persisted
    mappings with ``path``, ``size_bytes``, and optional ``sha256``/``media_type``.
    Relative paths are interpreted from ``media_dir``. Unregistered existing
    files are snapshots only; an unchanged stale file can never become success.
    """
    media_dir = Path(media_dir)
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise PipelineOfflineError("media work directory is unavailable") from None

    reusable, registrations_complete = _registered_media_files(media_dir, registered_files)
    if reusable and registrations_complete:
        logger.info("%s media receipt reused %d registered file(s)", platform, len(reusable))
        return DownloadResult("reused", reusable, None)

    before = _snapshot(media_dir)
    _invoke_downloader(platform, url, media_dir)
    written = _new_media_files(media_dir, before)
    if not written:
        raise PipelineOfflineError(f"{platform} downloader produced no newly written original media")
    result = DownloadResult("downloaded", written, _completed_at())
    logger.info("%s media receipt downloaded %d validated file(s)", platform, len(result.files))
    return result


def _find_video(media_dir: Path) -> str:
    """Legacy helper retained for callers that only need one media path."""
    candidates = _original_media_paths(Path(media_dir))
    for path in candidates:
        if path.suffix.lower() in _VIDEO_EXTENSIONS:
            return str(path)
    raise PipelineOfflineError("download produced no video file")


def download(platform: str, url: str, media_dir: Path) -> str:
    """Backward-compatible string API; archive-aware callers use download_with_result."""
    result = download_with_result(platform, url, media_dir)
    for item in result.files:
        if item.media_type == "video":
            return str(item.path)
    return str(result.files[0].path)
