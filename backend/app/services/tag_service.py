"""tags 业务：列表（含作品数）/ 按标签查作品。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.repositories import tag_repo, work_repo
from app.schemas.tag import Tag
from app.schemas.work import WorkPage
from app.services.work_service import _serialize_work


def _to_schema(tag, work_count: int = 0) -> Tag:
    data = Tag.model_validate(tag).model_dump()
    data["work_count"] = work_count
    return Tag(**data)


class TagService:
    def list(self, db: Session, kind: str | None) -> list[Tag]:
        return [_to_schema(t, c) for t, c in tag_repo.list_tags(db, kind)]

    def works(self, db: Session, tag_name: str, page: int, limit: int) -> WorkPage:
        tag = tag_repo.get_by_name(db, tag_name)
        if tag is None:
            raise not_found("TAG_NOT_FOUND")
        items, total = work_repo.list_by_tag(db, tag.id, page=page, limit=limit)
        return WorkPage(
            items=[_serialize_work(w) for w in items],
            total=total,
            page=page,
            limit=limit,
            has_more=page * limit < total,
        )


tag_service = TagService()
