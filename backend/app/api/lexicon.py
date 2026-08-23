"""lexicon 路由：/api/v1/lexicon*。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.schemas.lexicon import LexiconCreate, LexiconUpdate
from app.services.lexicon_service import lexicon_service

router = APIRouter(prefix="/api/v1/lexicon", tags=["lexicon"], dependencies=[Depends(require_admin)])


@router.get("", status_code=200)
def list_lexicon(db: Session = Depends(get_db)):
    return ok({"items": [e.model_dump() for e in lexicon_service.list(db)]})


@router.post("", status_code=201)
def create_lexicon_entry(payload: LexiconCreate, db: Session = Depends(get_db)):
    entry = lexicon_service.create(db, payload)
    return ok(entry.model_dump())


@router.patch("/{entry_id}", status_code=200)
def update_lexicon_entry(entry_id: int, payload: LexiconUpdate, db: Session = Depends(get_db)):
    entry = lexicon_service.update(db, entry_id, payload)
    return ok(entry.model_dump())


@router.delete("/{entry_id}", status_code=200)
def delete_lexicon_entry(entry_id: int, db: Session = Depends(get_db)):
    return ok(lexicon_service.delete(db, entry_id))
