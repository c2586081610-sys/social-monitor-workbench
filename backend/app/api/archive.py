"""Authenticated routes for local archive indexing and registered file access."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.core.errors import ok
from app.schemas.archive import ArchiveMetadataPatch, ArchiveScanRequest
from app.services import archive_service


router = APIRouter(
    prefix="/api/v1/archive",
    tags=["archive"],
    dependencies=[Depends(require_admin)],
)


def _filters(
    platform: str | None = Query(default=None),
    creator_id: int | None = Query(default=None, ge=1),
    group_id: int | None = Query(default=None, ge=1),
    work_id: list[int] | None = Query(default=None),
    root_key: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=200),
    check_status: str | None = Query(default=None),
    time_field: str = Query(default="published_at"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    include_unknown_time: bool = Query(default=False),
    unknown_time_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
):
    return archive_service.build_archive_filters(
        platform=platform,
        creator_id=creator_id,
        group_id=group_id,
        work_id=work_id,
        root_key=root_key,
        q=q,
        check_status=check_status,
        time_field=time_field,
        date_from=date_from,
        date_to=date_to,
        include_unknown_time=include_unknown_time,
        unknown_time_only=unknown_time_only,
        page=page,
        limit=limit,
    )


@router.get("", status_code=200)
def list_archive(filters=Depends(_filters), db: Session = Depends(get_db)):
    return ok(archive_service.list_archive_entries(db, filters))


@router.get("/policy", status_code=200)
def get_archive_policy():
    return ok(archive_service.archive_policy())


@router.get("/export.csv", status_code=200)
def export_archive(filters=Depends(_filters), db: Session = Depends(get_db)):
    payload = archive_service.export_archive_csv(db, filters)
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="archive.csv"'},
    )


@router.post("/scan", status_code=202)
def create_archive_scan(payload: ArchiveScanRequest, db: Session = Depends(get_db)):
    job = archive_service.create_scan_job(
        db,
        root_key=payload.root_key,
        relative_directory=payload.relative_directory,
    )
    return ok(archive_service.job_payload(job))


@router.get("/jobs/{job_id}", status_code=200)
def get_archive_job(job_id: str, db: Session = Depends(get_db)):
    return ok(archive_service.get_archive_job(db, job_id))


@router.get("/{archive_id}/info.csv", status_code=200)
def export_archive_entry_csv(archive_id: int, db: Session = Depends(get_db)):
    payload = archive_service.entry_info_csv(db, archive_id)
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="info.csv"'},
    )


@router.get("/{archive_id}/files/{file_id}", status_code=200)
def get_archive_file(archive_id: int, file_id: str, db: Session = Depends(get_db)):
    path, media_type, name = archive_service.archive_file(db, archive_id, file_id)
    return FileResponse(path, media_type=media_type, filename=name, content_disposition_type="inline")


@router.post("/{archive_id}/refresh", status_code=202)
def refresh_archive_entry(archive_id: int, db: Session = Depends(get_db)):
    job = archive_service.create_entry_job(db, archive_id, "refresh")
    return ok(archive_service.job_payload(job))


@router.get("/{archive_id}", status_code=200)
def get_archive_entry(archive_id: int, db: Session = Depends(get_db)):
    return ok(archive_service.archive_detail(db, archive_id))


@router.patch("/{archive_id}/metadata", status_code=200)
def patch_archive_entry(
    archive_id: int,
    payload: ArchiveMetadataPatch,
    db: Session = Depends(get_db),
):
    return ok(archive_service.patch_archive_metadata(db, archive_id, payload))


@router.post("/{archive_id}/sync", status_code=202)
def sync_archive_entry(archive_id: int, db: Session = Depends(get_db)):
    job = archive_service.create_entry_job(db, archive_id, "sync")
    return ok(archive_service.job_payload(job))
