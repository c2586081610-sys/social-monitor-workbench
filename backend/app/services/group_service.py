"""groups 业务：列表/创建/重命名/删除（删除时博主与作品移入未分组）。"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.repositories import creator_repo, group_repo
from app.schemas.group import Group


def _to_schema(group, creator_count: int = 0) -> Group:
    data = Group.model_validate(group).model_dump()
    data["creator_count"] = creator_count
    return Group(**data)


class GroupService:
    def list(self, db: Session) -> list[Group]:
        return [_to_schema(g, c) for g, c in group_repo.list_groups(db)]

    def create(self, db: Session, name: str) -> Group:
        if group_repo.get_by_name(db, name):
            raise conflict("GROUP_DUPLICATE")
        try:
            group = group_repo.create(db, name)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise conflict("GROUP_DUPLICATE") from None
        return _to_schema(group)

    def rename(self, db: Session, group_id: int, name: str) -> Group:
        group = group_repo.get(db, group_id)
        if group is None:
            raise not_found("GROUP_NOT_FOUND")
        existing = group_repo.get_by_name(db, name)
        if existing is not None and existing.id != group_id:
            raise conflict("GROUP_DUPLICATE")
        group = group_repo.rename(db, group, name)
        db.commit()
        return _to_schema(group)

    def delete(self, db: Session, group_id: int) -> dict:
        group = group_repo.get(db, group_id)
        if group is None:
            raise not_found("GROUP_NOT_FOUND")
        moved_creators = creator_repo.move_all_to_ungrouped(db, group_id)
        group_repo.clear_works_group(db, group_id)
        group_repo.delete(db, group)
        db.commit()
        return {"deleted": True, "moved_creators": moved_creators}


group_service = GroupService()
