"""cookies（凭据健康度）与 poll_logs（轮询日志）数据访问。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CookieHealth, PollLog
from app.utils.timeutil import now_iso


# ---------- cookies ----------
def get_cookie(db: Session, platform: str) -> CookieHealth | None:
    return db.execute(
        select(CookieHealth).where(CookieHealth.platform == platform)
    ).scalar_one_or_none()


def list_cookies(db: Session) -> list[CookieHealth]:
    return list(db.execute(select(CookieHealth).order_by(CookieHealth.id)).scalars().all())


def upsert_cookie(
    db: Session,
    platform: str,
    status: str,
    note: str | None = None,
    last_checked_at: str | None = None,
    expires_at: str | None = None,
) -> CookieHealth:
    cookie = get_cookie(db, platform)
    if cookie is None:
        cookie = CookieHealth(platform=platform, status=status)
        db.add(cookie)
    cookie.status = status
    cookie.note = note
    if last_checked_at is not None:
        cookie.last_checked_at = last_checked_at
    if expires_at is not None:
        cookie.expires_at = expires_at
    db.flush()
    return cookie


# ---------- poll_logs ----------
def create_poll_log(
    db: Session,
    platform: str,
    status: str,
    detail: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> PollLog:
    log = PollLog(
        platform=platform,
        status=status,
        detail=detail,
        started_at=started_at or now_iso(),
        finished_at=finished_at or now_iso(),
    )
    db.add(log)
    db.flush()
    return log


def latest_poll_logs(db: Session) -> dict[str, PollLog]:
    """按平台取最近一次轮询日志（平台级上次爬取时间，poll-status 数据源）。

    排序按 (platform, finished_at desc, id desc)，取每平台首条即最新。
    """
    rows = db.execute(
        select(PollLog)
        .order_by(PollLog.platform, PollLog.finished_at.desc().nullslast(), PollLog.id.desc())
    ).scalars().all()
    latest: dict[str, PollLog] = {}
    for log in rows:
        latest.setdefault(log.platform, log)
    return latest
