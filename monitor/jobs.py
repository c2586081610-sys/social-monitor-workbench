"""监控层任务：心跳、轮询、trigger 消费、可选流水线执行。"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

# 先导入 shared_db（把 backend 加入 sys.path），再导入 app.* 与 monitor.*
from monitor.store.shared_db import SessionLocal, settings  # noqa: E402

from app.models import Creator, Work  # noqa: E402
from app.repositories import health_repo, lexicon_repo, task_repo, work_repo  # noqa: E402
from app.utils.filename import sanitize_filename  # noqa: E402
from app.utils.timeutil import now_iso, to_date  # noqa: E402

from monitor.pipeline import download, frames, notify, transcribe  # noqa: E402
from monitor.pipeline.download import PipelineOfflineError  # noqa: E402
from monitor.platforms.douyin_cdp import DouyinCDPSession  # noqa: E402
from monitor.platforms.douyin_mediacrawler import DouyinMediaCrawlerAdapter  # noqa: E402
from monitor.platforms.rsshub import RSSHubError, RSSHubRouterAdapter  # noqa: E402

logger = logging.getLogger("monitor.jobs")

RSSHUB_PLATFORMS = ("bilibili", "xhs", "twitter")


def write_heartbeat() -> None:
    """写心跳文件：聚合 API 依据其新鲜度判断监控层在线。"""
    settings.workbuddy_dir.mkdir(parents=True, exist_ok=True)
    settings.monitor_heartbeat_file.write_text(
        json.dumps({"ts": time.time(), "pid": os.getpid()}), encoding="utf-8"
    )


def _update_cookie(db: Session, platform: str, status: str, note: str | None) -> None:
    health_repo.upsert_cookie(db, platform, status, note=note, last_checked_at=now_iso())


def _upsert_creator_entries(db: Session, creator: Creator, entries: list[dict]) -> int:
    """把某博主最新作品增量落库 + 登记 parse 任务，返回新增数；更新 last_poll_at。"""
    new_count = 0
    for item in entries:
        media_urls = item.get("media_urls")
        work = work_repo.upsert(
            db,
            item["platform"],
            item["external_id"],
            title=item["title"],
            url=item["url"],
            published_at=item.get("published_at"),
            creator_id=creator.id,
            source_type="monitor",
            content_type=item.get("content_type", "video"),
            media_urls=json.dumps(media_urls, ensure_ascii=False) if media_urls else None,
        )
        if work.status == "NEW":
            new_count += 1
            task_repo.upsert(db, work.id, "parse", "pending")
            work.status = "QUEUED"
            creator.last_work_at = now_iso()
    creator.last_poll_at = now_iso()
    return new_count


def poll_rsshub_platform(platform: str) -> None:
    """单平台轮询：拉取启用博主 → 增量 upsert 新作品 → 登记 parse 任务。"""
    adapter = RSSHubRouterAdapter(settings.rsshub_base_url)
    if not adapter.is_configured():
        logger.warning("RSSHUB_BASE_URL 未配置，跳过 %s 轮询", platform)
        return
    started = now_iso()
    with SessionLocal() as db:
        creators = db.execute(
            select(Creator).where(Creator.platform == platform, Creator.enabled == 1)
        ).scalars().all()
        total_new = 0
        for creator in creators:
            try:
                entries = adapter.fetch_entries(platform, creator.external_id)
            except RSSHubError as exc:
                _update_cookie(db, platform, "WARN", exc.message)
                health_repo.create_poll_log(db, platform, "fail", detail=exc.category, started_at=started)
                db.commit()
                logger.warning("%s 轮询失败 category=%s msg=%s", platform, exc.category, exc.message)
                continue
            new_count = _upsert_creator_entries(db, creator, entries)
            total_new += new_count
            db.commit()
            if new_count:
                logger.info("%s 博主 %s 新增 %d 条", platform, creator.name, new_count)
        _update_cookie(db, platform, "OK", None)
        health_repo.create_poll_log(db, platform, "ok", detail=None, started_at=started, new_works=total_new)
        db.commit()


def poll_rsshub_creator(creator_id: int) -> None:
    """单博主轮询（一次性爬取用）：按 creator.platform 走 RSSHub per-user 路由。

    复用 _upsert_creator_entries 完成增量落库 + 登记 parse 任务，并更新 last_poll_at；
    成功/失败均写 poll_logs（platform 级）。
    """
    adapter = RSSHubRouterAdapter(settings.rsshub_base_url)
    if not adapter.is_configured():
        logger.warning("RSSHUB_BASE_URL 未配置，跳过博主 %s", creator_id)
        return
    started = now_iso()
    with SessionLocal() as db:
        creator = db.get(Creator, creator_id)
        if creator is None:
            raise ValueError(f"creator {creator_id} 不存在")
        platform = creator.platform
        if platform not in RSSHUB_PLATFORMS:
            logger.warning("平台 %s 无 RSSHub 路由，跳过博主 %s", platform, creator_id)
            health_repo.create_poll_log(db, platform, "fail", detail="no_rsshub_route", started_at=started)
            db.commit()
            return
        try:
            entries = adapter.fetch_entries(platform, creator.external_id)
        except RSSHubError as exc:
            _update_cookie(db, platform, "WARN", exc.message)
            health_repo.create_poll_log(db, platform, "fail", detail=exc.category, started_at=started)
            db.commit()
            logger.warning("博主 %s 轮询失败 category=%s msg=%s", creator.name, exc.category, exc.message)
            return
        new_count = _upsert_creator_entries(db, creator, entries)
        _update_cookie(db, platform, "OK", None)
        health_repo.create_poll_log(db, platform, "ok", detail=None, started_at=started, new_works=new_count)
        db.commit()
        if new_count:
            logger.info("博主 %s 新增 %d 条", creator.name, new_count)


def poll_douyin() -> None:
    """抖音监测：复用 MediaCrawler 登录态 + DouYinClient 抓首页最新（低风控，替代 CDP 占位）。

    无 MediaCrawler/无 cookie → fail（poll_logs 记 detail）；单博主异常不阻塞其余。
    """
    adapter = DouyinMediaCrawlerAdapter(settings.mediacrawler_dir)
    started = now_iso()
    with SessionLocal() as db:
        if not adapter.available():
            msg = "MediaCrawler 未就绪（tools/mediacrawler 缺失或 COOKIES 为空，可用 tools/export_dy_cookie.py 导出）"
            _update_cookie(db, "douyin", "UNKNOWN", msg)
            health_repo.create_poll_log(db, "douyin", "failed", detail=msg, started_at=started)
            db.commit()
            return
        creators = db.execute(
            select(Creator).where(Creator.platform == "douyin", Creator.enabled == 1)
        ).scalars().all()
        total_new = 0
        ok_count = 0
        for creator in creators:
            sec_uid = creator.external_id or ""
            if not sec_uid:
                continue
            try:
                entries = adapter.poll_creator(sec_uid)
            except Exception as e:  # noqa: BLE001  单博主失败不阻塞其余
                logger.warning("douyin 博主 %s 爬取异常: %s", creator.name, e)
                health_repo.create_poll_log(db, "douyin", "fail", detail=f"mediacrawler 异常: {str(e)[:120]}", started_at=started)
                continue
            total_new += _upsert_creator_entries(db, creator, entries)
            ok_count += 1
        _update_cookie(db, "douyin", "OK" if ok_count else "FAIL", "MediaCrawler 监测")
        health_repo.create_poll_log(db, "douyin", "ok" if ok_count else "fail", detail=None, started_at=started, new_works=total_new)
        db.commit()


def consume_triggers() -> None:
    """消费聚合 API /monitor/poll 写下的 trigger 文件，处理完即删除。"""
    trigger_dir: Path = settings.trigger_dir
    if not trigger_dir.exists():
        return
    for path in sorted(trigger_dir.glob("poll-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            continue
        platform = payload.get("platform")
        if platform:
            if platform in RSSHUB_PLATFORMS:
                poll_rsshub_platform(platform)
            elif platform == "douyin":
                poll_douyin()
            else:
                logger.warning("未知平台 trigger: %s", platform)
        else:
            for p in RSSHUB_PLATFORMS:
                poll_rsshub_platform(p)
            poll_douyin()
        path.unlink(missing_ok=True)


def _work_media_dir(work) -> Path:
    """计算媒体目录 media/{分组}/{博主}/{日期}-{标题}/（SPEC §8 命名规则）。"""
    group = work.group.name if work.group else "未分组"
    creator = work.creator.name if work.creator else work.external_id
    date = to_date(work.published_at) or to_date(work.created_at) or "unknown"
    rel = Path(sanitize_filename(group)) / sanitize_filename(creator) / f"{date}-{sanitize_filename(work.title)}"
    return settings.media_root / rel


def run_pipeline() -> None:
    """处理 NEW/QUEUED 作品：下载→转写→抽帧→素材就绪清单；失败落 FAILED 可重试（AC-8）。"""
    if not settings.monitor_run_pipeline:
        return
    with SessionLocal() as db:
        works = db.execute(
            select(Work).where(Work.status.in_(["NEW", "QUEUED"])).order_by(Work.id).limit(10)
        ).scalars().all()
        for work in works:
            try:
                _process_work(db, work)
                db.commit()
            except PipelineOfflineError as exc:
                work.status = "FAILED"
                work.last_error = str(exc)
                task_repo.mark_failed(db, work.id, "download", str(exc))
                db.commit()
                logger.warning("work %s 流水线离线: %s", work.id, exc)
            except Exception as exc:  # noqa: BLE001
                work.status = "FAILED"
                work.last_error = str(exc)
                task_repo.mark_failed(db, work.id, "pipeline", str(exc))
                db.commit()
                logger.exception("work %s 流水线异常", work.id)


def _process_work(db: Session, work) -> None:
    """单作品流水线。v0.4：按 content_type 分流——
    video 走原五步（下载→转写→抽帧→就绪）；image/text（推特图文）走
    下载图片→写 manifest→跳过转写/抽帧→直接进 AI 笔记。
    """
    media_dir = _work_media_dir(work)
    content_type = work.content_type or "video"
    if content_type != "video":
        _process_image_work(db, work, media_dir)
        return

    video_path = download.download(work.platform, work.url, media_dir)
    work.status = "DOWNLOADING"
    work.media_path = str(media_dir.relative_to(settings.media_root)).replace("\\", "/")
    task_repo.upsert(db, work.id, "download", "succeeded", attempts=1)

    work.status = "TRANSCRIBING"
    transcript_dir = media_dir / "transcript"
    transcript_path = transcribe.transcribe(video_path, transcript_dir)
    work.transcript_path = str(Path(transcript_path).relative_to(settings.media_root)).replace("\\", "/")
    task_repo.upsert(db, work.id, "transcribe", "succeeded", attempts=1)

    work.status = "FRAME_EXTRACTING"
    frames_dir = media_dir / "frames"
    entries = [
        {"term": e.term, "action": e.action, "weight": e.weight, "enabled": bool(e.enabled)}
        for e in lexicon_repo.list_entries(db)
        if e.enabled
    ]
    segments = _load_segments(work.transcript_path)
    windows = frames.match_windows(segments, entries) if segments else []
    extracted = frames.extract_frames(video_path, windows, frames_dir)
    manifest_path = frames.write_manifest(work.id, extracted, frames_dir)
    work.frame_manifest_path = str(manifest_path.relative_to(settings.media_root)).replace("\\", "/")
    task_repo.upsert(db, work.id, "frames", "succeeded", attempts=1)

    work.status = "NOTE_GENERATING"
    notify.notify_ready(db, work)


def _process_image_work(db: Session, work, media_dir: Path) -> None:
    """图文作品：curl_cffi 下载图片清单 → 写 manifest → 直接进入 AI 笔记阶段。"""
    from monitor.pipeline import twitter_image

    work.status = "DOWNLOADING"
    work.media_path = str(media_dir.relative_to(settings.media_root)).replace("\\", "/")
    images_dir = media_dir / "images"
    try:
        manifest_path = twitter_image.download_images(work, images_dir)
    except Exception as exc:  # noqa: BLE001
        work.status = "FAILED"
        work.last_error = f"图文下载失败: {exc}"
        task_repo.mark_failed(db, work.id, "download", str(exc))
        logger.exception("work %s 图文下载异常", work.id)
        return
    work.frame_manifest_path = str(manifest_path.relative_to(settings.media_root)).replace("\\", "/")
    task_repo.upsert(db, work.id, "download", "succeeded", attempts=1)

    work.status = "NOTE_GENERATING"
    notify.notify_ready(db, work)


def _load_segments(transcript_rel: str | None) -> list[dict]:
    """读取带时间戳转写稿 [{start,end,text}]；损坏/空返回 []（K15 空文本降级）。"""
    if not transcript_rel:
        return []
    path = settings.media_root / transcript_rel
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return payload
    segments = payload.get("segments")
    return segments if isinstance(segments, list) else []
