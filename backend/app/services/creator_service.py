"""creators 业务：添加/修改/删除/详情。"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found, validation
from app.repositories import creator_repo, group_repo, work_repo
from app.schemas.creator import Creator, CreatorDetail, CreatorPage, CreatorUpdate
from app.schemas.work import WorkSummary


def _to_schema(creator) -> Creator:
    return Creator.model_validate(creator)


class CreatorService:
    def create(self, db: Session, payload) -> Creator:
        if payload.group_id is not None and group_repo.get(db, payload.group_id) is None:
            raise validation("GROUP_NOT_FOUND")
        if creator_repo.get_by_platform_external(db, payload.platform, payload.external_id):
            raise conflict("CREATOR_DUPLICATE")
        try:
            creator = creator_repo.create(
                db,
                platform=payload.platform,
                name=payload.name,
                profile_url=payload.profile_url,
                external_id=payload.external_id,
                group_id=payload.group_id,
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise conflict("CREATOR_DUPLICATE") from None
        return _to_schema(creator)

    def update(self, db: Session, creator_id: int, payload: CreatorUpdate) -> Creator:
        creator = creator_repo.get(db, creator_id)
        if creator is None:
            raise not_found("CREATOR_NOT_FOUND")
        fields = {}
        if payload.name is not None:
            fields["name"] = payload.name
        if payload.enabled is not None:
            fields["enabled"] = 1 if payload.enabled else 0
        if "group_id" in payload.model_fields_set:
            group_id = payload.group_id
            if group_id is not None and group_repo.get(db, group_id) is None:
                raise validation("GROUP_NOT_FOUND")
            fields["group_id"] = group_id
        creator = creator_repo.update(db, creator, **fields)
        db.commit()
        return _to_schema(creator)

    def delete(self, db: Session, creator_id: int) -> dict:
        creator = creator_repo.get(db, creator_id)
        if creator is None:
            raise not_found("CREATOR_NOT_FOUND")
        creator_repo.delete(db, creator)
        db.commit()
        return {"deleted": True}

    def get(self, db: Session, creator_id: int) -> CreatorDetail:
        creator = creator_repo.get(db, creator_id)
        if creator is None:
            raise not_found("CREATOR_NOT_FOUND")
        recent = work_repo.recent_by_creator(db, creator_id, limit=5)
        base = _to_schema(creator).model_dump()
        base["recent_works"] = [
            WorkSummary.model_validate(w).model_dump() for w in recent
        ]
        return CreatorDetail(**base)

    def list(self, db: Session, group_id, platform, q, page, limit) -> CreatorPage:
        items, total = creator_repo.list_creators(
            db, group_id=group_id, platform=platform, q=q, page=page, limit=limit
        )
        return CreatorPage(
            items=[_to_schema(c) for c in items],
            total=total,
            page=page,
            limit=limit,
            has_more=page * limit < total,
        )


creator_service = CreatorService()
