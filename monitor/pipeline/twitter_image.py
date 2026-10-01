"""Twitter/X image downloads with complete-album archive receipts."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from curl_cffi import requests as cffi_requests

from .download_result import DownloadResult, MediaFile

logger = logging.getLogger("monitor.pipeline.twitter_image")
DEFAULT_PROXY = os.getenv("TWITTER_PROXY", "http://127.0.0.1:7892")
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
_TWIMG_HOST = "twimg.com"


class TwitterImageError(Exception):
    """An image album failed validation or could not be completed."""


def _session() -> cffi_requests.Session:
    session = cffi_requests.Session(impersonate="chrome120")
    session.proxies = {"http": DEFAULT_PROXY, "https": DEFAULT_PROXY}
    return session


def _valid_image_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and (host == _TWIMG_HOST or host.endswith("." + _TWIMG_HOST))
        and port in (None, 443)
    )


def _image_suffix(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
        return ".avif"
    return None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".part", dir=path.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except OSError:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _safe_image_path(images_dir: Path, path: Path) -> Path:
    base = images_dir.absolute()
    candidate = path if path.is_absolute() else base / path
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("image receipt leaves its work directory") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("image receipt path is invalid")
    current = base
    try:
        if _is_reparse(current.lstat()):
            raise ValueError("image work directory cannot be a link")
    except OSError as exc:
        raise ValueError("image work directory is unavailable") from exc
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise ValueError("image receipt is unavailable") from exc
        if _is_reparse(info):
            raise ValueError("image receipt cannot traverse links")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("image receipt path contains a non-directory component")
        if index == len(relative.parts) - 1 and not stat.S_ISREG(info.st_mode):
            raise ValueError("image receipt is not a regular file")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(base.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("image receipt leaves its work directory") from exc
    return resolved


def _is_reparse(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x0400)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registered_image_records(
    images_dir: Path, registered_files: Iterable[MediaFile | Mapping[str, Any]]
) -> dict[Path, MediaFile]:
    valid: dict[Path, MediaFile] = {}
    for item in registered_files or ():
        if isinstance(item, MediaFile):
            raw_path, expected_size, declared_type, expected_hash = (
                item.path, item.size_bytes, item.media_type, item.sha256
            )
        elif isinstance(item, Mapping):
            raw_path = item.get("path", item.get("relative_path"))
            expected_size = item.get("size_bytes")
            declared_type = item.get("media_type")
            expected_hash = item.get("sha256")
            if raw_path is None or isinstance(expected_size, bool) or not isinstance(expected_size, int):
                raise TwitterImageError("registered image record is invalid")
        else:
            raise TwitterImageError("registered image record is invalid")
        path_value = Path(str(raw_path))
        if path_value.suffix.lower() not in _IMAGE_EXTENSIONS or declared_type not in {None, "image"}:
            continue
        try:
            path = _safe_image_path(images_dir, path_value)
            info = path.stat()
            if expected_size <= 0 or info.st_size <= 0 or info.st_size != expected_size:
                continue
            digest = _sha256(path) if expected_hash else None
            if expected_hash and digest.lower() != str(expected_hash).lower():
                continue
            if path.stat().st_size != info.st_size:
                continue
        except (OSError, ValueError):
            continue
        valid[path] = MediaFile(path, info.st_size, "image", digest or expected_hash)
    return valid


def _registered_album_matches(
    images_dir: Path,
    urls: list[str],
    registered: Mapping[Path, MediaFile],
) -> tuple[MediaFile, ...] | None:
    manifest_path = images_dir / "frame_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    frames = manifest.get("frames") if isinstance(manifest, dict) else None
    if not isinstance(frames, list) or len(frames) != len(urls):
        return None
    files: list[MediaFile] = []
    for url, frame in zip(urls, frames, strict=True):
        if not isinstance(frame, dict) or frame.get("source_url") != url:
            return None
        name = frame.get("file")
        if not isinstance(name, str) or Path(name).name != name:
            return None
        try:
            path = _safe_image_path(images_dir, Path(name))
        except (OSError, ValueError):
            return None
        file = registered.get(path)
        if file is None:
            return None
        files.append(file)
    return tuple(files)


def download_image(session, url: str, out_dir: Path, index: int) -> dict | None:
    """Download and validate one original image; never follow external redirects."""
    if not _valid_image_url(url):
        logger.warning("Twitter image source was rejected (item %s)", index)
        return None
    try:
        response = session.get(url, timeout=30, allow_redirects=False)
        response.raise_for_status()
        content = response.content
    except Exception as exc:  # noqa: BLE001
        logger.warning("Twitter image request failed (item %s, %s)", index, type(exc).__name__)
        return None
    suffix = _image_suffix(content) if content else None
    if suffix is None:
        logger.warning("Twitter image response was not a supported nonempty image (item %s)", index)
        return None
    filename = f"{index:03d}{suffix}"
    target = out_dir / filename
    try:
        _atomic_write(target, content)
    except OSError:
        logger.warning("Twitter image could not be written (item %s)", index)
        return None
    return {"file": filename, "source_url": url}


def _load_urls(work) -> list[str]:
    raw = getattr(work, "media_urls", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raw = None
    if not isinstance(raw, list):
        return []
    return [value if isinstance(value, str) else "" for value in raw]


def _media_file(images_dir: Path, name: str) -> MediaFile:
    path = _safe_image_path(images_dir, Path(name))
    info = path.stat()
    if info.st_size <= 0:
        raise TwitterImageError("image album contains an empty file")
    try:
        with path.open("rb") as stream:
            signature = stream.read(32)
    except OSError as exc:
        raise TwitterImageError("image album file could not be validated") from exc
    if _image_suffix(signature) is None:
        raise TwitterImageError("image album contains an invalid image file")
    after_hash = _sha256(path)
    after = path.stat()
    if after.st_size != info.st_size or after.st_mtime_ns != info.st_mtime_ns:
        raise TwitterImageError("image album changed during validation")
    return MediaFile(path, after.st_size, "image", after_hash)


def _write_manifest(path: Path, work_id: int | None, frames: list[dict], *, fallback: bool) -> None:
    payload = {
        "work_id": work_id,
        "semantic_aligned": False,
        "fallback": fallback,
        "frames": frames,
        "media_type": "image",
    }
    try:
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    except OSError as exc:
        raise TwitterImageError("image manifest could not be written") from exc


def download_images_with_result(
    work,
    images_dir: Path,
    *,
    registered_files: Iterable[MediaFile | Mapping[str, Any]] = (),
) -> tuple[Path, DownloadResult]:
    """Return (manifest path, receipt); image albums succeed only when complete.

    A saved manifest and file list are both required to reuse an album. Every
    source URL must match in order, and each reused file must still match its
    registered nonempty size/hash. Partial albums raise without an archive receipt.
    """
    images_dir = Path(images_dir)
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TwitterImageError("image work directory is unavailable") from exc
    try:
        if _is_reparse(images_dir.lstat()):
            raise TwitterImageError("image work directory cannot be a link")
    except FileNotFoundError:
        raise TwitterImageError("image work directory is unavailable") from None

    urls = _load_urls(work)
    content_type = str(getattr(work, "content_type", "") or "").lower()
    platform = str(getattr(work, "platform", "") or "").lower()
    manifest_path = images_dir / "frame_manifest.json"
    if content_type == "image" and platform != "twitter":
        raise TwitterImageError("this image adapter supports Twitter/X media only")
    if urls and platform != "twitter":
        raise TwitterImageError("this image adapter supports Twitter/X media only")
    if not urls:
        if content_type != "text":
            raise TwitterImageError("image work has no expected source images")
        _write_manifest(manifest_path, getattr(work, "id", None), [], fallback=True)
        return manifest_path, DownloadResult("not_required", (), None)
    if any(not _valid_image_url(url) for url in urls):
        raise TwitterImageError("image album contains an invalid source URL")

    registered = _registered_image_records(images_dir, registered_files)
    reused = _registered_album_matches(images_dir, urls, registered)
    if reused is not None:
        frames = _load_manifest_frames(manifest_path)
        _write_manifest(manifest_path, getattr(work, "id", None), frames, fallback=False)
        return manifest_path, DownloadResult("reused", reused, None)

    written: list[MediaFile] = []
    frames: list[dict] = []
    failed = 0
    new_count = 0
    session = _session()
    try:
        for index, url in enumerate(urls, start=1):
            registered_file = _registered_file_for_manifest_index(images_dir, index, url, registered)
            if registered_file is not None:
                written.append(registered_file)
                frames.append({"file": registered_file.path.name, "source_url": url})
                continue
            item = download_image(session, url, images_dir, index)
            if item is None:
                failed += 1
                continue
            try:
                verified_file = _media_file(images_dir, item["file"])
            except (OSError, ValueError, TwitterImageError):
                failed += 1
                continue
            written.append(verified_file)
            frames.append(item)
            new_count += 1
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass

    if failed or len(frames) != len(urls) or len(written) != len(urls):
        raise TwitterImageError(f"image album is incomplete ({len(written)}/{len(urls)} images validated)")

    # Mixed registered + new albums are a new download receipt; only the
    # completed full album is publishable and gets a completion timestamp.
    _write_manifest(manifest_path, getattr(work, "id", None), frames, fallback=False)
    if new_count == 0:
        return manifest_path, DownloadResult("reused", tuple(written), None)
    result = DownloadResult("downloaded", tuple(written), _completed_at())
    logger.info("Twitter image receipt downloaded %d/%d validated image(s)", len(written), len(urls))
    return manifest_path, result


def _load_manifest_frames(manifest_path: Path) -> list[dict]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    frames = manifest.get("frames") if isinstance(manifest, dict) else None
    return frames if isinstance(frames, list) and all(isinstance(item, dict) for item in frames) else []


def _registered_file_for_manifest_index(
    images_dir: Path, index: int, url: str, registered: Mapping[Path, MediaFile]
) -> MediaFile | None:
    for frame in _load_manifest_frames(images_dir / "frame_manifest.json"):
        if frame.get("source_url") != url or not isinstance(frame.get("file"), str):
            continue
        name = frame["file"]
        if Path(name).name != name:
            continue
        try:
            path = _safe_image_path(images_dir, Path(name))
        except (OSError, ValueError):
            continue
        if path.stem == f"{index:03d}":
            return registered.get(path)
    return None


def download_images(work, images_dir: Path) -> Path:
    """Legacy manifest-only API; archive callers should use with_result."""
    manifest_path, _result = download_images_with_result(work, images_dir)
    return manifest_path


def retry_write_text(path: Path, content, binary: bool = False) -> None:
    """Compatibility helper retained for older image-pipeline callers."""
    data = content if binary else str(content).encode("utf-8")
    _atomic_write(Path(path), data)


def _completed_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
