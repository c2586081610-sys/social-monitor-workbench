"""works 路由：/api/v1/works*（列表/详情/重试/分析/归类/关键帧）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.schemas.link_analysis import NoteCompletionRequest
from app.schemas.work import ClassifyRequest
from app.services.link_analysis_service import link_analysis_service
from app.services.classify_service import classify_service
from app.services.note_service import note_service
from app.services.work_service import work_service

router = APIRouter(prefix="/api/v1/works", tags=["works"], dependencies=[Depends(require_admin)])


@router.get("", status_code=200)
def list_works(
    db: Session = Depends(get_db),
    group_id: int | None = Query(default=None, ge=1),
    creator_id: int | None = Query(default=None, ge=1),
    tag: str | None = Query(default=None, max_length=50),
    platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    unclassified: bool = Query(default=False),
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
):
    result = work_service.list(
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
    return ok(result.model_dump())


@router.get("/{work_id}", status_code=200)
def get_work(work_id: int, db: Session = Depends(get_db)):
    detail = work_service.get_detail(db, work_id)
    return ok(detail.model_dump())


@router.get("/{work_id}/local-view", status_code=200)
def get_work_local_view(work_id: int, db: Session = Depends(get_db)):
    """作品本地视图：原文件链接 + 本地文件清单 + AI 总结（笔记全文）。"""
    return ok(work_service.local_view(db, work_id))


@router.post("/{work_id}/retry", status_code=200)
def retry_work(work_id: int, db: Session = Depends(get_db)):
    work = work_service.retry(db, work_id)
    return ok(work.model_dump())


@router.post("/{work_id}/analyze", status_code=200)
def analyze_work(work_id: int, db: Session = Depends(get_db)):
    return ok(note_service.analyze(db, work_id))


@router.post("/{work_id}/complete-note", status_code=200)
def complete_note(work_id: int, payload: NoteCompletionRequest, db: Session = Depends(get_db)):
    return ok(link_analysis_service.complete_note(db, work_id, payload.note_path).model_dump())


@router.post("/{work_id}/classify", status_code=200)
def classify_work(work_id: int, payload: ClassifyRequest, db: Session = Depends(get_db)):
    work = classify_service.classify(db, work_id, payload.group_id, payload.tags, payload.creator_id)
    return ok(work.model_dump())


@router.get("/{work_id}/frames", status_code=200)
def list_work_frames(work_id: int, db: Session = Depends(get_db)):
    return ok(work_service.frames(db, work_id))
