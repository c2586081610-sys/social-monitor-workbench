"""lexicon 词库业务：CRUD。"""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.repositories import lexicon_repo
from app.schemas.lexicon import LexiconItem


def _to_schema(entry) -> LexiconItem:
    return LexiconItem.model_validate(entry)


class LexiconService:
    def list(self, db: Session) -> list[LexiconItem]:
        return [_to_schema(e) for e in lexicon_repo.list_entries(db)]

    def create(self, db: Session, payload) -> LexiconItem:
        if lexicon_repo.get_by_term(db, payload.term):
            raise conflict("LEXICON_DUPLICATE")
        try:
            entry = lexicon_repo.create(
                db,
                term=payload.term,
                action=payload.action,
                weight=payload.weight,
                enabled=1 if payload.enabled else 0,
                platform_scope=payload.platform_scope,
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise conflict("LEXICON_DUPLICATE") from None
        return _to_schema(entry)

    def update(self, db: Session, entry_id: int, payload) -> LexiconItem:
        entry = lexicon_repo.get(db, entry_id)
        if entry is None:
            raise not_found("LEXICON_NOT_FOUND")
        fields = {}
        if payload.term is not None:
            fields["term"] = payload.term
        if payload.action is not None:
            fields["action"] = payload.action
        if payload.weight is not None:
            fields["weight"] = payload.weight
        if payload.enabled is not None:
            fields["enabled"] = 1 if payload.enabled else 0
        if "platform_scope" in payload.model_fields_set:
            fields["platform_scope"] = payload.platform_scope
        try:
            entry = lexicon_repo.update(db, entry, **fields)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise conflict("LEXICON_DUPLICATE") from None
        return _to_schema(entry)

    def delete(self, db: Session, entry_id: int) -> dict:
        entry = lexicon_repo.get(db, entry_id)
        if entry is None:
            raise not_found("LEXICON_NOT_FOUND")
        lexicon_repo.delete(db, entry)
        db.commit()
        return {"deleted": True}


lexicon_service = LexiconService()
