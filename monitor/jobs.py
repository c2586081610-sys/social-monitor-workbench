"""监控层任务：心跳、轮询、trigger 消费、可选流水线执行。"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

# 先导入 shared_db（把 backend 加入 sys.path），再导入 app.* 与 monitor.*
from monitor.store.shared_db import SessionLocal, settings  # noqa: E402

from app.models import ArchiveEntry, Creator, Work  # noqa: E402
from app.repositories import health_repo, lexicon_repo, task_repo, work_repo  # noqa: E402
from app.repositories import archive_repo  # noqa: E402
from app.services.archive_checkpoint_service import (  # noqa: E402
    archive_metadata_seed,
    assert_work_archive_identity,
    publication_provenance_from_work,
    record_download_checkpoint,
    register_legacy_media,
    resolve_work_directory,
)
from app.services.archive_metadata_resolver import resolve_archive_metadata  # noqa: E402
from app.services.archive_sync_service import sync_archive_entry  # noqa: E402
from app.utils.archive_paths import relative_path_from_root, resolve_archive_path  # noqa: E402
from app.utils.timeutil import now_iso  # noqa: E402

from monitor.pipeline import download, frames, notify, transcribe  # noqa: E402
from monitor.pipeline.download import PipelineOfflineError  # noqa: E402
from monitor.platforms.douyin_cdp import DouyinCDPSession  # noqa: E402
from monitor.platforms.douyin_mediacrawler import DouyinMediaCrawlerAdapter  # noqa: E402
from monitor.platforms.rsshub import RSSHubError, RSSHubRouterAdapter  # noqa: E402
from monitor.platforms.xhs_mediacrawler import XhsMediacrawlerAdapter  # noqa: E402

logger = logging.getLogger("monitor.jobs")

RSSHUB_PLATFORMS = ("bilibili", "twitter")


def _producer_time_fields(item: dict) -> dict:
    """Accept only publication fields that name a real source and precision."""
    fields = {}
    raw = item.get("published_at")
    source = item.get("published_time_source")
    precision = item.get("published_time_precision")
    source_timezone = item.get("published_time_timezone")
    if isinstance(raw, str) and raw and isinstance(source, str) and source.strip() and precision in {"day", "minute", "second"}:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.year > 1970:
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    if precision != "day" or not isinstance(source_timezone, str):
                        raise ValueError("publication source timezone missing")
                    parsed = parsed.replace(tzinfo=ZoneInfo(source_timezone))
                if not isinstance(source_timezone, str) or not source_timezone.strip():
                    source_timezone = "UTC"
                else:
                    ZoneInfo(source_timezone)
                fields.update({
                    "published_at": raw,
                    "published_time_source": source.strip(),
                    "published_time_precision": precision,
                    "published_time_timezone": source_timezone,
                })
        except (ValueError, TypeError, ZoneInfoNotFoundError, OverflowError, OSError):
            pass

    checked_at = item.get("metadata_checked_at")
    if isinstance(checked_at, str) and checked_at:
        try:
            checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
            if checked.year > 1970 and checked.tzinfo is not None and checked.utcoffset() is not None:
                fields["metadata_checked_at"] = checked.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    return fields


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
        fields = {
            "title": item["title"],
            "url": item["url"],
            "creator_id": creator.id,
            "source_type": "monitor",
            "content_type": item.get("content_type", "video"),
        }
        fields.update(_producer_time_fields(item))
        if isinstance(media_urls, list):
            fields["media_urls"] = json.dumps(media_urls, ensure_ascii=False)
        if "cover_url" in item:
            fields["cover_url"] = item.get("cover_url")
        work = work_repo.upsert(
            db,
            item["platform"],
            item["external_id"],
            **fields,
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


def _poll_xhs_creators(db, creators) -> int:
    """遍历小红书博主抓最新笔记并落库，返回新增数。"""
    adapter = XhsMediacrawlerAdapter()
    total_new = 0
    for creator in creators:
        profile_url = creator.profile_url or ""
        if not profile_url:
            continue
        try:
            entries = adapter.poll_creator(profile_url)
        except Exception as e:  # noqa: BLE001  单博主失败不阻塞其余
            logger.warning("xhs 博主 %s 爬取异常: %s", creator.name, e)
            continue
        total_new += _upsert_creator_entries(db, creator, entries)
    return total_new


def poll_xhs() -> None:
    """小红书监测：Playwright 拦截 user_posted API 抓博主最新笔记（替代 RSSHub xhs 路由）。"""
    adapter = XhsMediacrawlerAdapter()
    started = now_iso()
    with SessionLocal() as db:
        if not adapter.available():
            msg = "xhs 抓取工具缺失（tools/xhs_fetch_notes.py）"
            _update_cookie(db, "xhs", "UNKNOWN", msg)
            health_repo.create_poll_log(db, "xhs", "failed", detail=msg, started_at=started)
            db.commit()
            return
        creators = db.execute(
            select(Creator).where(Creator.platform == "xhs", Creator.enabled == 1)
        ).scalars().all()
        try:
            total_new = _poll_xhs_creators(db, creators)
        except Exception as e:  # noqa: BLE001
            logger.warning("xhs 轮询整体异常: %s", e)
            _update_cookie(db, "xhs", "FAIL", f"xhs 异常: {str(e)[:80]}")
            health_repo.create_poll_log(db, "xhs", "failed", detail=f"xhs 异常: {str(e)[:120]}", started_at=started)
            db.commit()
            return
        _update_cookie(db, "xhs", "OK", "xhs 拦截监测")
        health_repo.create_poll_log(db, "xhs", "ok", detail=None, started_at=started, new_works=total_new)
        db.commit()


def poll_xhs_creator(creator_id: int) -> None:
    """单博主小红书立即爬取（onetime --creator 用）。"""
    started = now_iso()
    with SessionLocal() as db:
        creator = db.get(Creator, creator_id)
        if creator is None or creator.platform != "xhs":
            health_repo.create_poll_log(db, "xhs", "fail", detail="creator_not_found", started_at=started)
            db.commit()
            return
        try:
            total_new = _poll_xhs_creators(db, [creator])
        except Exception as e:  # noqa: BLE001
            health_repo.create_poll_log(db, "xhs", "fail", detail=f"xhs 异常: {str(e)[:120]}", started_at=started)
            db.commit()
            return
        health_repo.create_poll_log(db, "xhs", "ok", detail=None, started_at=started, new_works=total_new)
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
            elif platform == "xhs":
                poll_xhs()
            else:
                logger.warning("未知平台 trigger: %s", platform)
        else:
            for p in RSSHUB_PLATFORMS:
                poll_rsshub_platform(p)
            poll_douyin()
            poll_xhs()
        path.unlink(missing_ok=True)


def _existing_archive_entry(db: Session, work: Work):
    entries = [entry for entry in archive_repo.list_by_work(db, work.id) if entry.root_key == "media"]
    if work.media_path:
        relative = relative_path_from_root("media", str(work.media_path))
        entry = archive_repo.get_entry_by_path(db, "media", relative)
        if entry is not None and entry.platform == work.platform and str(entry.external_id or "") == str(work.external_id):
            return entry
        return None
    entries = [
        entry for entry in entries
        if entry.platform == work.platform and str(entry.external_id or "") == str(work.external_id)
    ]
    if not entries:
        return None
    return next((entry for entry in entries if entry.check_status == "verified"), entries[0])


def _resolve_work_metadata(db: Session, work: Work):
    """Resolve stored and available publisher evidence before choosing a new path."""
    existing_entry = _existing_archive_entry(db, work)
    seed = archive_metadata_seed(work, existing_entry)
    stored_source = seed.get("published_time_source")
    stored_precision = seed.get("published_time_precision")
    already_detailed = stored_source == "bilibili_view_api" and stored_precision == "second"
    resolution = resolve_archive_metadata(
        work,
        existing_metadata=seed,
        query_bilibili_detail=(work.platform == "bilibili" and not already_detailed),
    )
    if resolution.title.verified and "title" not in resolution.conflicts and resolution.title.value:
        work.title = str(resolution.title.value)
    publication = resolution.published_at
    if publication.verified and "published_at" not in resolution.conflicts and publication.value:
        work.published_at = str(publication.value)
        work.published_time_source = publication.source
        work.published_time_precision = publication.precision
        if publication.source_timezone:
            work.published_time_timezone = publication.source_timezone
        elif publication.precision == "second":
            work.published_time_timezone = "UTC"
    if resolution.metadata_checked_at:
        work.metadata_checked_at = resolution.metadata_checked_at
    return resolution, existing_entry


def _work_media_dir(work, publication_provenance=None, existing_entry=None) -> Path:
    """Resolve the stored physical directory or build a stable new archive name."""
    _relative, path = resolve_work_directory(
        work,
        root_key="media",
        publication_provenance=publication_provenance,
        existing_entry=existing_entry,
    )
    return path


def _registered_files_for_adapter(entry, relative_directory: str, *, images_only: bool = False) -> list[dict]:
    registered = []
    for item in entry.files_json or []:
        if not isinstance(item, dict):
            continue
        relative = item.get("relative_path")
        if not isinstance(relative, str):
            continue
        relative = relative.replace("\\", "/")
        prefix = relative_directory.rstrip("/") + "/"
        if not os.path.normcase(relative).startswith(os.path.normcase(prefix)):
            raise ValueError("registered media leaves its work directory")
        work_relative = relative[len(prefix):]
        if images_only and not os.path.normcase(work_relative).startswith(os.path.normcase("images/")):
            raise ValueError("image work conflicts with a non-image media registration")
        absolute = resolve_archive_path("media", relative)
        registered.append({
            "path": str(absolute),
            "size_bytes": item.get("size_bytes"),
            "media_type": item.get("media_type"),
            "sha256": item.get("sha256"),
        })
    return registered


def _sync_checkpoint_after_commit(entry_id: int, work_id: int) -> None:
    try:
        sync_archive_entry(entry_id)
    except Exception as exc:  # noqa: BLE001 - the durable pending job retries it
        logger.warning("archive sidecar sync deferred work_id=%s error_type=%s", work_id, type(exc).__name__)


def _pipeline_error_message(exc: Exception) -> str:
    if isinstance(exc, PipelineOfflineError):
        return str(exc)
    try:
        from monitor.pipeline.twitter_image import TwitterImageError

        if isinstance(exc, TwitterImageError):
            return str(exc)
    except ImportError:
        pass
    return f"download checkpoint failed ({type(exc).__name__})"


@dataclass(frozen=True)
class _DownloadCheckpoint:
    media_dir: Path
    result: object
    manifest_path: Path | None = None


def download_and_checkpoint(db: Session, work: Work) -> _DownloadCheckpoint:
    """Download/reuse, persist Work + ArchiveEntry + sync job, then sync sidecars.

    The checkpoint commit occurs before the independent sync call. Callers may
    safely begin transcription only after this function returns.
    """
    resolution, existing_entry = _resolve_work_metadata(db, work)
    publication = resolution.publication_provenance() or publication_provenance_from_work(work)
    source_context = resolution.as_metadata()
    # Keep newly checked publication evidence even when the later downloader
    # fails; a cached Work value is never passed back as a fresh collector.
    db.commit()

    relative_directory, media_dir = resolve_work_directory(
        work,
        root_key="media",
        publication_provenance=publication,
        existing_entry=existing_entry,
    )
    registered_entry = archive_repo.get_entry_by_path(db, "media", relative_directory)
    assert_work_archive_identity(db, registered_entry, work)

    try:
        legacy = register_legacy_media(
            db,
            work,
            root_key="media",
            publication_provenance=publication,
            source_context=source_context,
        )
        if legacy is not None:
            db.commit()
            _sync_checkpoint_after_commit(legacy.archive_entry_id, work.id)
            registered_entry = db.get(ArchiveEntry, legacy.archive_entry_id)
            registered_files = list(legacy.files)
        else:
            registered_entry = archive_repo.get_entry_by_path(db, "media", relative_directory)
            assert_work_archive_identity(db, registered_entry, work)
            registered_files = (
                _registered_files_for_adapter(
                    registered_entry,
                    relative_directory,
                    images_only=(str(work.content_type or "").lower() in {"image", "text"}),
                )
                if registered_entry is not None else []
            )

        work.status = "DOWNLOADING"
        prior_task = task_repo.get_by_work_stage(db, work.id, "download")
        attempts = (prior_task.attempts if prior_task is not None else 0) + 1
        task = task_repo.upsert(db, work.id, "download", "running", attempts=attempts)
        task.error = None
        db.commit()

        manifest_path = None
        content_type = str(work.content_type or "video").lower()
        if content_type == "video":
            result = download.download_with_result(
                work.platform,
                work.url,
                media_dir,
                registered_files=registered_files,
            )
            download_source = f"monitor.pipeline.download:{work.platform}"
        else:
            from monitor.pipeline import twitter_image

            images_dir = media_dir / "images"
            manifest_path, result = twitter_image.download_images_with_result(
                work,
                images_dir,
                registered_files=registered_files,
            )
            download_source = "monitor.pipeline.twitter_image"
            work.frame_manifest_path = relative_path_from_root("media", str(manifest_path))

        entry_id = record_download_checkpoint(
            db,
            work,
            result,
            root_key="media",
            download_source=download_source,
            publication_provenance=publication,
            source_context=source_context,
        )
        task_repo.upsert(db, work.id, "download", "succeeded", attempts=attempts)
        work.last_error = None
        db.commit()
        _sync_checkpoint_after_commit(entry_id, work.id)
        return _DownloadCheckpoint(media_dir=media_dir, result=result, manifest_path=manifest_path)
    except Exception as exc:  # noqa: BLE001 - preserve safe failure state and leave no receipt
        safe_message = _pipeline_error_message(exc)
        work.status = "FAILED"
        work.last_error = safe_message
        task_repo.mark_failed(db, work.id, "download", safe_message)
        db.commit()
        if isinstance(exc, PipelineOfflineError):
            raise
        raise PipelineOfflineError(safe_message) from None


def process_link_analysis(work_id: int) -> dict[str, str | int]:
    """只处理用户刚提交的一条视频作品，不依赖也不触发全局队列。"""
    with SessionLocal() as db:
        work = db.get(Work, work_id)
        if work is None or work.status not in {"NEW", "QUEUED", "FAILED"}:
            raise ValueError(f"work {work_id} is not runnable")
        if (work.content_type or "video") != "video":
            work.status = "FAILED"
            work.last_error = "链接分析仅支持视频作品"
            task_repo.mark_failed(db, work.id, "download", work.last_error)
            db.commit()
            return {"work_id": work.id, "status": work.status}
        try:
            _process_work(db, work, write_pending=False)
            db.commit()
        except PipelineOfflineError as exc:
            failed_stage = "transcribe" if work.status == "TRANSCRIBING" else "download"
            work.status = "FAILED"
            work.last_error = str(exc)
            task_repo.mark_failed(db, work.id, failed_stage, str(exc))
            db.commit()
            logger.warning("link analysis %s pipeline offline: %s", work.id, exc)
        except Exception as exc:  # noqa: BLE001
            failed_stage = "transcribe" if work.status == "TRANSCRIBING" else "pipeline"
            work.status = "FAILED"
            work.last_error = str(exc)
            task_repo.mark_failed(db, work.id, failed_stage, str(exc))
            db.commit()
            logger.exception("link analysis %s pipeline failed", work.id)
        return {"work_id": work.id, "status": work.status}


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
                _process_work(db, work, write_pending=True)
                db.commit()
            except PipelineOfflineError as exc:
                failed_stage = "transcribe" if work.status == "TRANSCRIBING" else "download"
                work.status = "FAILED"
                work.last_error = str(exc)
                task_repo.mark_failed(db, work.id, failed_stage, str(exc))
                db.commit()
                logger.warning("work %s 流水线离线: %s", work.id, exc)
            except Exception as exc:  # noqa: BLE001
                failed_stage = {
                    "DOWNLOADING": "download",
                    "TRANSCRIBING": "transcribe",
                    "FRAME_EXTRACTING": "frames",
                }.get(work.status, "pipeline")
                work.status = "FAILED"
                work.last_error = str(exc)
                task_repo.mark_failed(db, work.id, failed_stage, str(exc))
                db.commit()
                logger.exception("work %s 流水线异常", work.id)


def _process_work(db: Session, work, *, write_pending: bool = True) -> None:
    """单作品流水线。v0.4：按 content_type 分流——
    video 走原五步（下载→转写→抽帧→就绪）；image/text（推特图文）走
    下载图片→写 manifest→跳过转写/抽帧→直接进 AI 笔记。
    """
    content_type = work.content_type or "video"
    checkpoint = download_and_checkpoint(db, work)
    if content_type != "video":
        work.status = "NOTE_GENERATING"
        if write_pending:
            notify.notify_ready(db, work)
        else:
            note_task = task_repo.upsert(db, work.id, "note", "pending", attempts=0)
            note_task.error = None
        return

    video_file = next((item for item in checkpoint.result.files if item.media_type == "video"), checkpoint.result.files[0])
    video_path = str(video_file.path)
    media_dir = checkpoint.media_dir

    work.status = "TRANSCRIBING"
    transcribe_task = task_repo.upsert(db, work.id, "transcribe", "running", attempts=1)
    transcribe_task.error = None
    transcript_dir = media_dir / "transcript"
    transcript_path = transcribe.transcribe(video_path, transcript_dir)
    work.transcript_path = relative_path_from_root("media", str(transcript_path))
    task_repo.upsert(db, work.id, "transcribe", "succeeded", attempts=1)

    work.status = "FRAME_EXTRACTING"
    frame_task = task_repo.upsert(db, work.id, "frames", "running", attempts=1)
    frame_task.error = None
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
    work.frame_manifest_path = relative_path_from_root("media", str(manifest_path))
    task_repo.upsert(db, work.id, "frames", "succeeded", attempts=1)

    work.status = "NOTE_GENERATING"
    if write_pending:
        notify.notify_ready(db, work)
    else:
        note_task = task_repo.upsert(db, work.id, "note", "pending", attempts=0)
        note_task.error = None


def _load_segments(transcript_rel: str | None) -> list[dict]:
    """读取带时间戳转写稿 [{start,end,text}]；损坏/空返回 []（K15 空文本降级）。"""
    if not transcript_rel:
        return []
    try:
        path = resolve_archive_path("media", relative_path_from_root("media", transcript_rel), must_exist=True)
    except (OSError, ValueError):
        return []
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
