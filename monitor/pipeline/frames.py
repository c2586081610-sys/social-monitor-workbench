"""流水线·语义对齐抽帧：词库命中 → 重点时间窗口 → ffmpeg 抽帧 → frame_manifest.json（SPEC §8.2）。

K20：同窗多词条、增删矛盾 → 取权重净额，冲突写日志。
无时间戳/空文本降级由上层处理（fallback 标记）。
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("monitor.pipeline.frames")


def match_windows(segments: list[dict], entries: list[dict]) -> list[dict]:
    """segments: [{start, end, text}]；entries: [{term, action, weight, enabled}] → 重点窗口。"""
    windows = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        hits = []
        for entry in entries:
            if not entry.get("enabled", True):
                continue
            term = entry.get("term", "")
            if term and term in text:
                hits.append(
                    {"term": term, "action": entry.get("action", "increase"), "weight": entry.get("weight", 1.0)}
                )
        if hits:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start + 1.0))
            windows.append({"start": start, "end": end, "hits": hits})
    return windows


def _frame_count_for_window(window: dict) -> int:
    net = sum(h["weight"] for h in window["hits"] if h["action"] == "increase") - sum(
        h["weight"] for h in window["hits"] if h["action"] == "decrease"
    )
    count = max(1, round(net))
    if net != round(net):
        logger.info("lexicon conflict resolved by net weight: %s", window["hits"])
    return count


def extract_frames(video_path: str, windows: list[dict], out_dir: Path) -> list[dict]:
    """ffmpeg 抽帧：每窗口默认 1 帧，increase 按权重增帧 / decrease 减帧（下限 1）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    idx = 1
    for window in windows:
        count = _frame_count_for_window(window)
        span = max(window["end"] - window["start"], 1.0)
        for k in range(count):
            t = window["start"] + span * (k + 0.5) / count
            name = f"frame_{idx:04d}.jpg"
            result = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", video_path, "-frames:v", "1", "-q:v", "3", str(out_dir / name)],
                capture_output=True,
            )
            if result.returncode == 0:
                frames.append(
                    {
                        "file": f"frames/{name}",
                        "time_seconds": round(t, 2),
                        "window_start": round(window["start"], 2),
                        "window_end": round(window["end"], 2),
                        "hits": window["hits"],
                        "confidence": 0.9,
                    }
                )
                idx += 1
            else:
                logger.warning("ffmpeg frame extract failed at %s", t)
    return frames


def write_manifest(work_id: int, frames: list[dict], out_dir: Path, semantic_aligned: bool = True, fallback: bool = False) -> Path:
    manifest = {
        "work_id": work_id,
        "semantic_aligned": semantic_aligned,
        "fallback": fallback,
        "frames": frames,
    }
    path = out_dir / "frame_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
