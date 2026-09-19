"""手动视频链接分析入口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.schemas.link_analysis import LinkAnalysisCreate
from app.services.link_analysis_service import link_analysis_service

router = APIRouter(
    prefix="/api/v1/link-analyses",
    tags=["link-analyses"],
    dependencies=[Depends(require_admin)],
)


@router.post("", status_code=201)
def create_link_analysis(payload: LinkAnalysisCreate, db: Session = Depends(get_db)):
    return ok(link_analysis_service.ingest(db, payload).model_dump())
