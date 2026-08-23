"""note 业务：生成/刷新「素材就绪清单」（workbuddy/pending/*.json，SPEC §10 契约）。"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import not_found
from app.repositories import task_repo, work_repo
from app.utils.filename import sanitize_filename
from app.utils.timeutil import to_date


def _creator_name(work) -> str:
    return work.creator.name if work.creator else work.external_id


def _group_name(work) -> str:
    return work.group.name if work.group else "待分组"


def write_pending_manifest(work) -> dict:
    """写 workbuddy/pending/{work_id}-{日期}-{标题}.json，返回相对工作区根路径。"""
    pending_dir: Path = settings.pending_dir
    pending_dir.mkdir(parents=True, exist_ok=True)

    date = to_date(work.published_at) or to_date(work.created_at) or "unknown"
    safe_title = sanitize_filename(work.title)
    safe_creator = sanitize_filename(_creator_name(work))
    group = _group_name(work)

    media_prefix = work.media_path or f"{group}/{safe_creator}/{date}-{safe_title}"
    transcript_path = work.transcript_path or f"{media_prefix}/transcript/transcript.json"
    frames_dir = f"{media_prefix}/frames"
    expected_output = f"Obsidian/{group}/{safe_creator}/{date}-{safe_title}.md"

    manifest = {
        "work_id": work.id,
        "platform": work.platform,
        "blogger": _creator_name(work),
        "title": work.title,
        "url": work.url,
        "publish_date": date,
        "transcript_path": transcript_path,
        "frames_dir": frames_dir,
        "lexicon_hits": [],  # 流水线抽帧后回填
        "expected_output": expected_output,
        "status": "pending",
    }
    filename = f"{work.id}-{date}-{safe_title}.json"
    path = pending_dir / filename
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        rel = str(path.relative_to(settings.workspace_root))
    except ValueError:
        # workbuddy 目录不在工作区根下（如测试临时目录）→ 按契约路径返回
        rel = str(Path("workbuddy") / "pending" / filename)
    return rel.replace("\\", "/")


class NoteService:
    def analyze(self, db: Session, work_id: int) -> dict:
        work = work_repo.get(db, work_id)
        if work is None:
            raise not_found("WORK_NOT_FOUND")
        pending_file = write_pending_manifest(work)
        work_repo.update(db, work, status="NOTE_GENERATING")
        task_repo.upsert(db, work_id, "note", "pending", error=None, attempts=0)
        db.commit()
        return {"note_pending": True, "pending_file": pending_file}


note_service = NoteService()
