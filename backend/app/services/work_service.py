"""works 业务：列表/详情/重试/关键帧/本地视图/串行化。"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import conflict, not_found
from app.models import ArchiveEntry
from app.repositories import task_repo, work_repo
from app.schemas.work import TaskStage, Work, WorkDetail, WorkPage
from app.utils.manifest import frame_count, manifest_items, read_manifest


def _abs_media(path: str | None) -> str | None:
    """将 /media/... 相对路径转为 MEDIA_BASE_URL 下的绝对 URL（前端跨源显示用）。"""
    if not path or not path.startswith("/"):
        return path
    base = settings.media_base_url
    if not base:
        return path  # 同源开发环境保留相对路径
    return f"{base}{path}"


_ARCHIVE_STATUS_PRIORITY = {"verified": 1, "needs_review": 2, "failed": 3, "conflict": 4}


def _archive_statuses(db: Session, work_ids: list[int]) -> dict[int, str]:
    """Read all linked physical-entry states in one query for a result page."""
    ids = sorted({work_id for work_id in work_ids if isinstance(work_id, int) and work_id > 0})
    if not ids:
        return {}
    rows = db.execute(
        select(ArchiveEntry.work_id, ArchiveEntry.check_status).where(ArchiveEntry.work_id.in_(ids))
    ).all()
    statuses: dict[int, str] = {}
    for work_id, status in rows:
        if status not in _ARCHIVE_STATUS_PRIORITY:
            continue
        current = statuses.get(work_id)
        if current is None or _ARCHIVE_STATUS_PRIORITY[status] > _ARCHIVE_STATUS_PRIORITY[current]:
            statuses[work_id] = status
    return statuses


def _serialize_work(work, archive_check_status: str | None = None) -> Work:
    data = Work.model_validate(work).model_dump()
    data["archive_check_status"] = archive_check_status
    data["frame_count"] = frame_count(settings.media_root, work.frame_manifest_path)
    data["cover_url"] = _abs_media(data.get("cover_url"))
    return Work(**data)


_IMG_PATTERN = re.compile(r'(!?\[[^\]]*\]\()([^)]+)\)')


def _resolve_note_images(note_abs: Path, md: str, media_root: Path) -> str:
    """把 Obsidian 笔记里的相对路径图片/链接解析为 /media/ 绝对 URL（供网页渲染）。"""

    def repl(m: re.Match) -> str:
        full = m.group(0)
        rel = m.group(2)
        if rel.startswith(("http://", "https://", "/", "data:", "#")):
            return full
        try:
            abs_path = (note_abs.parent / rel).resolve()
            abs_path.relative_to(media_root)
            url = "/media/" + abs_path.relative_to(media_root).as_posix()
            return f"{m.group(1)}{url})"
        except (ValueError, OSError):
            return full

    return _IMG_PATTERN.sub(repl, md)


class WorkService:
    def list(self, db: Session, *, group_id, creator_id, tag, platform, status, source_type, unclassified, q, page, limit) -> WorkPage:
        items, total = work_repo.list_works(
            db,
            group_id=group_id,
            creator_id=creator_id,
            tag=tag,
            platform=platform,
            status=status,
            source_type=source_type,
            unclassified=unclassified,
            q=q,
            page=page,
            limit=limit,
        )
        statuses = _archive_statuses(db, [work.id for work in items])
        return WorkPage(
            items=[_serialize_work(w, statuses.get(w.id)) for w in items],
            total=total,
            page=page,
            limit=limit,
            has_more=page * limit < total,
        )

    def unclassified(self, db: Session, page: int, limit: int) -> WorkPage:
        items, total = work_repo.list_unclassified(db, page=page, limit=limit)
        statuses = _archive_statuses(db, [work.id for work in items])
        return WorkPage(
            items=[_serialize_work(w, statuses.get(w.id)) for w in items],
            total=total,
            page=page,
            limit=limit,
            has_more=page * limit < total,
        )

    def list_by_creator(self, db: Session, creator_id: int, page: int, limit: int) -> WorkPage:
        if not _creator_exists(db, creator_id):
            raise not_found("CREATOR_NOT_FOUND")
        items, total = work_repo.list_by_creator(db, creator_id, page=page, limit=limit)
        statuses = _archive_statuses(db, [work.id for work in items])
        return WorkPage(
            items=[_serialize_work(w, statuses.get(w.id)) for w in items],
            total=total,
            page=page,
            limit=limit,
            has_more=page * limit < total,
        )

    def get_detail(self, db: Session, work_id: int) -> WorkDetail:
        work = work_repo.get(db, work_id)
        if work is None:
            raise not_found("WORK_NOT_FOUND")
        archive_status = _archive_statuses(db, [work.id]).get(work.id)
        base = _serialize_work(work, archive_status).model_dump()
        base["tags"] = [{"id": t.id, "name": t.name, "kind": t.kind} for t in work.tags]
        base["stages"] = [
            TaskStage.model_validate(t).model_dump() for t in task_repo.list_by_work(db, work_id)
        ]
        base["transcript_path"] = work.transcript_path
        base["frame_manifest_path"] = work.frame_manifest_path
        return WorkDetail(**base)

    def local_view(self, db: Session, work_id: int) -> dict:
        """作品本地视图：原文件链接 + 本地文件清单 + AI 总结（Obsidian 笔记全文，图片路径解析为 /media）。"""
        work = work_repo.get(db, work_id)
        if work is None:
            raise not_found("WORK_NOT_FOUND")
        media_root = settings.media_root.resolve()

        # ① 本地文件清单（media_path 兼容含/不含 media/ 前缀）
        files: list[dict] = []
        if work.media_path:
            raw = work.media_path.replace("\\", "/")
            if raw.startswith("media/"):
                raw = raw[len("media/"):]
            base = media_root / raw
            try:
                if base.is_dir():
                    for f in sorted(base.rglob("*")):
                        if f.is_file():
                            rel = f.relative_to(media_root).as_posix()
                            files.append(
                                {
                                    "name": f.name,
                                    "size": f.stat().st_size,
                                    "path": rel,
                                    "url": _abs_media(f"/media/{rel}") or f"/media/{rel}",
                                }
                            )
                elif base.is_file():
                    rel = base.relative_to(media_root).as_posix()
                    files.append({"name": base.name, "size": base.stat().st_size, "path": rel, "url": _abs_media(f"/media/{rel}") or f"/media/{rel}"})
            except OSError:
                pass

        # ② AI 总结：Obsidian 笔记全文 + 相对路径图片解析
        note_content: str | None = None
        if work.note_path:
            note_rel = work.note_path.replace("\\", "/")
            if note_rel.startswith("Obsidian/"):
                note_rel = note_rel[len("Obsidian/"):]
            note_abs = settings.obsidian_root / note_rel
            if note_abs.exists():
                note_content = note_abs.read_text(encoding="utf-8", errors="ignore")
                note_content = _resolve_note_images(note_abs, note_content, media_root)

        return {
            "id": work.id,
            "title": work.title,
            "platform": work.platform,
            "url": work.url,
            "note_path": work.note_path,
            "media_files": files,
            "note_content": note_content,
        }

    def retry(self, db: Session, work_id: int) -> Work:
        work = work_repo.get(db, work_id)
        if work is None:
            raise not_found("WORK_NOT_FOUND")
        if work.status != "FAILED":
            raise conflict("NOT_RETRYABLE")
        work = work_repo.update(
            db, work, status="QUEUED", last_error=None, retry_count=work.retry_count + 1
        )
        task_repo.upsert(db, work.id, "download", "pending", attempts=0)
        db.commit()
        archive_status = _archive_statuses(db, [work.id]).get(work.id)
        return _serialize_work(work, archive_status)

    def frames(self, db: Session, work_id: int) -> dict:
        work = work_repo.get(db, work_id)
        if work is None:
            raise not_found("WORK_NOT_FOUND")
        manifest = read_manifest(settings.media_root, work.frame_manifest_path)
        if manifest is None:
            return {"semantic_aligned": False, "fallback": False, "items": []}
        return {
            "semantic_aligned": bool(manifest.get("semantic_aligned", False)),
            "fallback": bool(manifest.get("fallback", False)),
            "items": manifest_items(manifest),
        }


def _creator_exists(db: Session, creator_id: int) -> bool:
    from app.repositories import creator_repo

    return creator_repo.get(db, creator_id) is not None


work_service = WorkService()
