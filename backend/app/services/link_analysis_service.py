"""用户明确提交的一条视频链接：校验身份并幂等创建手动作品。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import not_found, validation
from app.repositories import task_repo, work_repo
from app.services.archive_metadata_resolver import resolve_archive_metadata
from app.schemas.link_analysis import LinkAnalysisCreate, LinkAnalysisResult
from app.schemas.work import Work as WorkSchema


@dataclass(frozen=True)
class LinkIdentity:
    platform: Literal["douyin", "bilibili", "xhs", "twitter"]
    external_id: str


_BILIBILI_ID = re.compile(r"/video/(BV[0-9A-Za-z]+)", re.I)
_DOUYIN_ID = re.compile(r"/video/(\d+)")
_XHS_ID = re.compile(r"/(?:explore|discovery/item)/([0-9a-zA-Z]+)")
_TWITTER_ID = re.compile(r"/status/(\d+)")
_SHORT_LINK_HOSTS = {"b23.tv", "v.douyin.com", "xhslink.com", "t.co"}


def _resolve_short_link(url: str) -> str:
    try:
        response = httpx.get(url, follow_redirects=True, timeout=10.0)
        return str(response.url)
    except httpx.HTTPError as exc:
        raise validation("LINK_REDIRECT_FAILED") from exc


def parse_link_identity(
    url: str, resolve_redirect: Callable[[str], str] | None = None
) -> LinkIdentity:
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except (AttributeError, TypeError, ValueError):
        raise validation("LINK_IDENTITY_UNSUPPORTED") from None
    host = parsed.hostname.lower() if parsed.hostname else ""
    path = parsed.path
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 80, 443)
    ):
        raise validation("LINK_IDENTITY_UNSUPPORTED")

    if host in _SHORT_LINK_HOSTS:
        resolved = resolve_redirect(url) if resolve_redirect else _resolve_short_link(url)
        return parse_link_identity(resolved)

    if host == "bilibili.com" or host.endswith(".bilibili.com"):
        match = _BILIBILI_ID.search(path)
        if match:
            return LinkIdentity("bilibili", match.group(1))
    elif host == "douyin.com" or host.endswith(".douyin.com"):
        match = _DOUYIN_ID.search(path)
        if match:
            return LinkIdentity("douyin", match.group(1))
    elif host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com"):
        match = _XHS_ID.search(path)
        if match:
            return LinkIdentity("xhs", match.group(1))
    elif host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
        match = _TWITTER_ID.search(path)
        if match:
            return LinkIdentity("twitter", match.group(1))
    raise validation("LINK_IDENTITY_UNSUPPORTED")


class LinkAnalysisService:
    def ingest(self, db: Session, request: LinkAnalysisCreate) -> LinkAnalysisResult:
        identity = parse_link_identity(request.url)
        if identity.platform != request.platform or identity.external_id != request.external_id:
            raise validation("LINK_IDENTITY_MISMATCH")

        existing = work_repo.get_by_platform_external(db, request.platform, request.external_id)
        if existing is not None:
            return LinkAnalysisResult(
                work=WorkSchema.model_validate(existing),
                created=False,
                mode=request.mode,
            )

        work = work_repo.upsert(
            db,
            request.platform,
            request.external_id,
            title=f"待解析 {request.external_id}",
            url=request.url,
            source_type="manual",
            content_type="video",
            status="QUEUED",
        )
        if identity.platform == "bilibili":
            resolution = resolve_archive_metadata(
                work,
                query_bilibili_detail=True,
            )
            if resolution.title.verified and "title" not in resolution.conflicts and resolution.title.value:
                work.title = str(resolution.title.value)
            publication = resolution.published_at
            if publication.verified and "published_at" not in resolution.conflicts and publication.value:
                work.published_at = str(publication.value)
                work.published_time_source = publication.source
                work.published_time_precision = publication.precision
                work.published_time_timezone = publication.source_timezone
            if resolution.metadata_checked_at:
                work.metadata_checked_at = resolution.metadata_checked_at
        for stage in ("parse", "download", "transcribe", "frames", "note"):
            task_repo.upsert(db, work.id, stage, "pending", attempts=0)
        db.commit()
        db.refresh(work)
        return LinkAnalysisResult(
            work=WorkSchema.model_validate(work),
            created=True,
            mode=request.mode,
        )

    def complete_note(self, db: Session, work_id: int, note_path: str) -> WorkSchema:
        relative = Path(note_path.replace("\\", "/"))
        if relative.is_absolute() or relative.drive:
            raise validation("NOTE_PATH_INVALID")
        root = settings.obsidian_root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise validation("NOTE_PATH_INVALID") from None
        if candidate.suffix.lower() != ".md" or not candidate.is_file():
            raise validation("NOTE_PATH_INVALID")

        work = work_repo.get(db, work_id)
        if work is None:
            raise not_found("WORK_NOT_FOUND")
        work_repo.update(
            db,
            work,
            note_path=candidate.relative_to(root).as_posix(),
            status="DONE",
        )
        task = task_repo.upsert(db, work.id, "note", "succeeded", attempts=1)
        task.error = None
        db.commit()
        db.refresh(work)
        return WorkSchema.model_validate(work)


link_analysis_service = LinkAnalysisService()
