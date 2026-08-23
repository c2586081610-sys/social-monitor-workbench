"""流水线·语义对齐抽帧：词库命中 → 重点时间窗口 → ffmpeg 抽帧 → frame_manifest.json（SPEC §8.2）。

K20：同窗多词条、增删矛盾 → 取权重净额，冲突写日志。
无时间戳/空文本降级由上层处理（fallback 标记）。

segments 契约：[{start, end, text}]（秒）。paraformer-zh 的 segments 即此形状；
若退化单段（transcript 标注 timestamps: none），match_windows 用 start/end 默认值兜底不报错。
extract_frames 入口同样做 ASCII 路径规范化（与转写同根因：中文/空格/问号路径 ffmpeg 失败）。
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from monitor.pipeline.paths import ensure_ascii_work_copy

logger = logging.getLogger("monitor.pipeline.frames")


def match_windows(segments: list[dict], entries: list[dict]) -> list[dict]:
    """segments: [{start, end, text}]；entries: [{term, action, weight, enabled}] → 重点窗口。

    - paraformer 句级 segments 直接消费（[{start,end,text}]，start/end 单位为秒）
    - 退化单段（无 start/end）时用默认值兜底，不抛错（K15 降级）
    """
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
            try:
                start = float(seg.get("start", 0.0))
            except (TypeError, ValueError):
                start = 0.0
            try:
                end = float(seg.get("end", start + 1.0))
            except (TypeError, ValueError):
                end = start + 1.0
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
    """ffmpeg 抽帧：每窗口默认 1 帧，increase 按权重增帧 / decrease 减帧（下限 1）。

    路径规范化：中文/空格/问号路径先复制到 media/_work/{hash}/ 再喂 ffmpeg
    （与转写同根因，规避 Windows 子进程非 ASCII 路径失败）。
    """
    work_path, _ = ensure_ascii_work_copy(video_path)
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
                ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", work_path, "-frames:v", "1", "-q:v", "3", str(out_dir / name)],
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
