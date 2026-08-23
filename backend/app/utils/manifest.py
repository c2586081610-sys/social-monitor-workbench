"""关键帧 manifest 读取（SPEC §8.2 契约），纯函数无副作用。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_manifest(media_root: str | Path, rel_path: str | None) -> dict | None:
    """读取 frame_manifest.json；不存在或损坏返回 None。"""
    if not rel_path:
        return None
    path = Path(media_root) / rel_path
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def frame_count(media_root: str | Path, rel_path: str | None) -> int:
    manifest = read_manifest(media_root, rel_path)
    if not manifest:
        return 0
    frames = manifest.get("frames")
    return len(frames) if isinstance(frames, list) else 0


def manifest_items(manifest: dict | None) -> list[dict[str, Any]]:
    if not manifest:
        return []
    frames = manifest.get("frames")
    return frames if isinstance(frames, list) else []
