"""临时续跑脚本 v2：B站 work id=2 转写→抽帧→pending，整体重试（每次重开 session）。

本机环境 aggregator.db 写存在间歇性 readonly（WorkBuddy 文件保护窗口），
重试策略：整步重试 + 新连接，规避窗口。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor.store.shared_db import SessionLocal  # noqa: E402
from app.repositories import lexicon_repo, task_repo  # noqa: E402
from monitor.pipeline import frames, notify, transcribe  # noqa: E402
from app.models import Work  # noqa: E402

MEDIA_ROOT = Path("media")
WORK_ID = 2
MEDIA_REL = Path("未分组/链路验证-莫梓艺大笑/2026-08-24-【B站链路验证】Attention 注意别喝多")
VIDEO = MEDIA_ROOT / MEDIA_REL / "Attention 注意别喝多.mp4"


def retry(fn, tries=10, delay=3):
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"[retry {i+1}/{tries}] {type(exc).__name__}: {str(exc)[:80]}")
            time.sleep(delay)


def step_transcribe():
    with SessionLocal() as db:
        work = db.get(Work, WORK_ID)
        work.status = "TRANSCRIBING"
        work.media_path = str(MEDIA_REL).replace("\\", "/")
        transcript_dir = MEDIA_ROOT / MEDIA_REL / "transcript"
        tp = transcribe.transcribe(str(VIDEO), transcript_dir)
        work.transcript_path = str(Path(tp).relative_to(MEDIA_ROOT)).replace("\\", "/")
        task_repo.upsert(db, work.id, "download", "succeeded", attempts=1)
        task_repo.upsert(db, work.id, "transcribe", "succeeded", attempts=1)
        db.commit()
        print("转写完成:", work.transcript_path)
        return work.transcript_path


def step_frames():
    with SessionLocal() as db:
        work = db.get(Work, WORK_ID)
        work.status = "FRAME_EXTRACTING"
        frames_dir = MEDIA_ROOT / MEDIA_REL / "frames"
        entries = [
            {"term": e.term, "action": e.action, "weight": e.weight, "enabled": bool(e.enabled)}
            for e in lexicon_repo.list_entries(db) if e.enabled
        ]
        print("词库词条:", len(entries))
        payload = json.loads((MEDIA_ROOT / work.transcript_path).read_text(encoding="utf-8"))
        segments = payload if isinstance(payload, list) else payload.get("segments", [])
        windows = frames.match_windows(segments, entries)
        extracted = frames.extract_frames(str(VIDEO), windows, frames_dir)
        manifest = frames.write_manifest(work.id, extracted, frames_dir)
        work.frame_manifest_path = str(manifest.relative_to(MEDIA_ROOT)).replace("\\", "/")
        task_repo.upsert(db, work.id, "frames", "succeeded", attempts=1)
        db.commit()
        print(f"抽帧完成: {len(extracted)} 帧")
        return work.frame_manifest_path


def step_notify():
    with SessionLocal() as db:
        work = db.get(Work, WORK_ID)
        work.status = "NOTE_GENERATING"
        pending = notify.notify_ready(db, work)
        db.commit()
        print("pending:", pending)
        return pending


if __name__ == "__main__":
    print("== 转写 ==")
    retry(step_transcribe)
    print("== 抽帧 ==")
    retry(step_frames)
    print("== pending ==")
    retry(step_notify)
    print("完成")
