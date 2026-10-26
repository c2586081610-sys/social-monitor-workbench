"""classify 业务：待分类手动归类（设分组 + 标签 + 可选绑博主），原子移动双目录。"""
from __future__ import annotations

import shutil
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import conflict, not_found, validation
from app.repositories import archive_repo, creator_repo, group_repo, tag_repo, task_repo, work_repo
from app.services.archive_checkpoint_service import ensure_archive_sync_job, publication_provenance_from_work
from app.services.archive_metadata_service import build_archive_metadata
from app.services.archive_sync_service import sync_archive_entry
from app.schemas.work import Work
from app.services.work_service import _serialize_work
from app.utils.filename import sanitize_filename

logger = logging.getLogger("app.services.classify")


def _first_segment(rel: str | None) -> str | None:
    if not rel:
        return None
    return rel.split("/", 1)[0]


def _relocate(rel: str | None, old_prefix: str, new_prefix: str) -> str | None:
    if not rel:
        return None
    return new_prefix + rel[len(old_prefix):]


class ClassifyService:
    def classify(self, db: Session, work_id: int, group_id: int, tags: list[str], creator_id: int | None) -> Work:
        work = work_repo.get(db, work_id)
        if work is None:
            raise not_found("WORK_NOT_FOUND")
        group = group_repo.get(db, group_id)
        if group is None:
            raise validation("GROUP_NOT_FOUND")

        if creator_id is not None:
            creator = creator_repo.get(db, creator_id)
            if creator is None:
                raise validation("CREATOR_NOT_FOUND")
            work.creator_id = creator_id
            work.creator = creator

        self._move_note(work, group.name)
        work.group_id = group_id
        work.group = group
        work.status = "DONE"

        if tags:
            work_repo.clear_work_tags(db, work.id)
            for name in tags:
                tag = tag_repo.get_by_name(db, name)
                if tag is None:
                    tag = tag_repo.create(db, name, kind="small")
                tag_repo.link_work(db, work.id, tag.id)

        task_repo.upsert(db, work.id, "note", "succeeded", error=None)
        sync_entry_ids = self._update_archive_metadata(db, work)
        db.commit()
        for entry_id in sync_entry_ids:
            try:
                sync_archive_entry(entry_id)
            except Exception as exc:  # noqa: BLE001 - pending sync job remains durable
                logger.warning("archive classification sync deferred entry_id=%s error_type=%s", entry_id, type(exc).__name__)
        return _serialize_work(work)

    def _move_note(self, work, new_group_name: str) -> None:
        """Keep the approved note relocation while media and transcript paths stay stable."""
        old_prefix = _first_segment(work.note_path) or _first_segment(work.media_path) or "待分组"
        new_prefix = sanitize_filename(new_group_name)
        if old_prefix == new_prefix:
            return
        rel = work.note_path
        if not rel:
            return
        relative = Path(str(rel).replace("\\", "/"))
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise validation("NOTE_PATH_INVALID")
        new_rel = _relocate(relative.as_posix(), old_prefix, new_prefix)
        root = settings.obsidian_root.resolve()
        src = (root / relative).resolve()
        dest = (root / Path(new_rel)).resolve()
        try:
            src.relative_to(root)
            dest.relative_to(root)
        except ValueError:
            raise validation("NOTE_PATH_INVALID") from None
        if src.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        elif src.exists() and dest.exists():
            raise conflict("CLASSIFY_TARGET_EXISTS")
        work.note_path = new_rel

    def _update_archive_metadata(self, db: Session, work) -> list[int]:
        """Persist metadata-only classification updates and recoverable sync jobs."""
        entry_ids = []
        publication = publication_provenance_from_work(work)
        source_context = {"metadata_checked_at": getattr(work, "metadata_checked_at", None)}
        for entry in archive_repo.list_by_work(db, work.id):
            fields = build_archive_metadata(
                work,
                entry.root_key,
                entry.relative_directory,
                existing=entry,
                publication_provenance=publication,
                source_context=source_context,
            )
            updated = archive_repo.upsert_entry(
                db,
                root_key=entry.root_key,
                relative_directory=entry.relative_directory,
                **fields,
            )
            ensure_archive_sync_job(db, updated)
            entry_ids.append(updated.id)
        return entry_ids


classify_service = ClassifyService()
