"""单链接执行器：不得触发全局队列或代替 Codex 生成笔记。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.repositories import task_repo, work_repo
from monitor import jobs


def _make_work(db, external_id: str, *, content_type: str = "video"):
    work = work_repo.upsert(
        db,
        "bilibili",
        external_id,
        title=f"执行器 {external_id}",
        url=f"https://www.bilibili.com/video/{external_id}",
        source_type="manual",
        content_type=content_type,
        status="QUEUED",
    )
    db.commit()
    return work


def test_runner_processes_only_requested_queued_work(monkeypatch, db):
    target = _make_work(db, "BV-run-target")
    untouched = _make_work(db, "BV-run-untouched")
    calls: list[tuple[int, bool]] = []

    monkeypatch.setattr(
        jobs,
        "_process_work",
        lambda session, work, *, write_pending: calls.append((work.id, write_pending)),
    )

    result = jobs.process_link_analysis(target.id)

    assert result == {"work_id": target.id, "status": "QUEUED"}
    assert calls == [(target.id, False)]
    db.refresh(untouched)
    assert untouched.status == "QUEUED"


def test_runner_marks_known_non_video_as_failed_without_pipeline(monkeypatch, db):
    work = _make_work(db, "BV-run-image", content_type="image")
    monkeypatch.setattr(jobs, "_process_work", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    result = jobs.process_link_analysis(work.id)

    assert result == {"work_id": work.id, "status": "FAILED"}
    db.refresh(work)
    assert "仅支持视频" in work.last_error
    assert task_repo.get_by_work_stage(db, work.id, "download").status == "failed"


def test_cli_delegates_only_the_requested_work_id(monkeypatch):
    from tools import process_link_analysis

    calls: list[int] = []
    monkeypatch.setattr(
        process_link_analysis.jobs,
        "process_link_analysis",
        lambda work_id: calls.append(work_id) or {"work_id": work_id, "status": "NOTE_GENERATING"},
    )
    monkeypatch.setattr(sys, "argv", ["process_link_analysis.py", "--work-id", "123"])

    assert process_link_analysis.main() == 0
    assert calls == [123]
