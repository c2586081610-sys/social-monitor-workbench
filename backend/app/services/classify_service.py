"""classify 业务：待分类手动归类（设分组 + 标签 + 可选绑博主），原子移动双目录。"""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import conflict, not_found, validation
from app.repositories import creator_repo, group_repo, tag_repo, task_repo, work_repo
from app.schemas.work import Work
from app.services.work_service import _serialize_work


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

        self._move_dirs(work, group.name)
        work.group_id = group_id
        work.status = "DONE"

        if tags:
            work_repo.clear_work_tags(db, work.id)
            for name in tags:
                tag = tag_repo.get_by_name(db, name)
                if tag is None:
                    tag = tag_repo.create(db, name, kind="small")
                tag_repo.link_work(db, work.id, tag.id)

        task_repo.upsert(db, work.id, "note", "succeeded", error=None)
        db.commit()
        return _serialize_work(work)

    def _move_dirs(self, work, new_group_name: str) -> None:
        """把 media 与 Obsidian 目录从旧前缀迁到新分组前缀；源不存在则跳过（P1 无文件场景）。"""
        old_prefix = _first_segment(work.media_path) or _first_segment(work.note_path) or "待分组"
        new_prefix = new_group_name
        if old_prefix == new_prefix:
            return
        for attr, root in (("media_path", settings.media_root), ("note_path", settings.obsidian_root)):
            rel = getattr(work, attr)
            if not rel:
                continue
            new_rel = _relocate(rel, old_prefix, new_prefix)
            src = Path(root) / rel
            dest = Path(root) / new_rel
            if src.exists() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
            elif src.exists() and dest.exists():
                raise conflict("CLASSIFY_TARGET_EXISTS")
            setattr(work, attr, new_rel)


classify_service = ClassifyService()
