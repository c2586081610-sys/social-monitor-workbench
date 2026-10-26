"""Threaded durable archive scanner, metadata refresher and sidecar worker."""
from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import ArchiveEntry, ArchiveJob
from app.repositories import archive_repo
from app.services.archive_metadata_resolver import resolve_archive_metadata
from app.services.archive_scan_service import (
    DirectoryScanError,
    ScanPlanError,
    build_scan_plan,
    build_work_indexes,
    read_scan_plan,
    refresh_curated_csv,
    safe_scan_error,
    scan_directory,
    work_directories_for_root,
)
from app.services.archive_sync_service import ArchiveSyncError, sync_archive_entry
from app.utils.archive_fingerprint import entry_content_fingerprint


logger = logging.getLogger("archive.worker")
_LEASE_SECONDS = 120
_HEARTBEAT_SECONDS = 25
_MAX_DIRECTORY_ATTEMPTS = 3
_STOP_JOIN_SECONDS = 30


class _LeaseLost(RuntimeError):
    pass


class ArchiveWorker:
    """One background thread per application process; DB leases fence workers."""

    def __init__(self, *, session_factory=SessionLocal, poll_seconds: float = 1.0) -> None:
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_lock = threading.Lock()
        self.worker_id = f"archive-{os.getpid()}-{uuid.uuid4().hex[:12]}"

    def start(self) -> None:
        with self._started_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="archive-worker",
                daemon=True,
            )
            self._thread.start()
            logger.info("archive worker started")

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=_STOP_JOIN_SECONDS)
        if thread is not None and thread.is_alive():
            logger.warning("archive worker shutdown deferred to lease recovery")
        else:
            logger.info("archive worker stopped")

    def _run(self) -> None:
        try:
            self._restore_pending_sync_intents()
        except Exception as exc:
            logger.warning("archive sync recovery skipped (%s)", type(exc).__name__)
        while not self._stop.is_set():
            job = None
            try:
                with self._session_factory() as db:
                    job = archive_repo.claim_next_job(
                        db,
                        worker_id=self.worker_id,
                        lease_seconds=_LEASE_SECONDS,
                    )
                    db.commit()
                if job is None:
                    self._stop.wait(self._poll_seconds)
                    continue
                self._execute_claimed_job(job.id, job.job_type)
            except Exception as exc:
                logger.warning("archive worker iteration failed (%s)", type(exc).__name__)
                self._stop.wait(self._poll_seconds)

    def _restore_pending_sync_intents(self) -> None:
        """Restore new pending intents without looping on identical failed syncs."""
        with self._session_factory() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            rows = db.execute(
                select(ArchiveEntry).where(ArchiveEntry.sync_status.in_(("pending", "failed")))
            ).scalars().all()
            for entry in rows:
                active = db.execute(
                    select(ArchiveJob.id).where(
                        ArchiveJob.job_type == "sync",
                        ArchiveJob.archive_entry_id == entry.id,
                        ArchiveJob.status.in_(("queued", "running")),
                    ).limit(1)
                ).scalar_one_or_none()
                if active is not None:
                    continue
                latest = db.execute(
                    select(ArchiveJob)
                    .where(ArchiveJob.job_type == "sync", ArchiveJob.archive_entry_id == entry.id)
                    .order_by(ArchiveJob.created_at.desc(), ArchiveJob.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                current_fingerprint = entry_content_fingerprint(entry)
                if (
                    latest is not None
                    and latest.status == "failed"
                    and (latest.cursor or {}).get("content_fingerprint") == current_fingerprint
                ):
                    continue
                if latest is None or latest.status in {"completed", "partial"} or (
                    latest.status == "failed"
                    and (latest.cursor or {}).get("content_fingerprint") != current_fingerprint
                ):
                    archive_repo.create_job(
                        db,
                        job_type="sync",
                        root_key=entry.root_key,
                        relative_directory=entry.relative_directory,
                        archive_entry_id=entry.id,
                        cursor={"content_fingerprint": current_fingerprint},
                        statistics={"attempts": 0, "recovered_intent": True},
                    )
            db.commit()

    def _execute_claimed_job(self, job_id: str, job_type: str) -> None:
        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(job_id, heartbeat_stop, lease_lost),
            name=f"archive-lease-{job_id[:8]}",
            daemon=True,
        )
        heartbeat.start()
        try:
            if job_type == "scan":
                self._process_scan(job_id, lease_lost)
            elif job_type == "refresh":
                self._process_refresh(job_id, lease_lost)
            elif job_type == "sync":
                self._process_sync(job_id, lease_lost)
            else:
                self._finish_job(job_id, status="failed", error="archive_job_type_invalid")
        except _LeaseLost:
            logger.info("archive job lease lost job=%s", job_id)
        except Exception as exc:
            error = f"archive_job_failed:{type(exc).__name__}"
            if self._stop.is_set():
                logger.info("archive job interrupted for shutdown job=%s", job_id)
            else:
                try:
                    self._finish_job(job_id, status="failed", error=error)
                except Exception as write_exc:
                    logger.warning("archive job failure checkpoint failed (%s)", type(write_exc).__name__)
                logger.warning("archive job failed job=%s error=%s", job_id, error)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
            if self._stop.is_set():
                self._requeue_owned_job(job_id)

    def _heartbeat(self, job_id: str, stop_event: threading.Event, lease_lost: threading.Event) -> None:
        while not stop_event.wait(_HEARTBEAT_SECONDS):
            now = datetime.now(timezone.utc)
            now_text = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            expires_text = (now + timedelta(seconds=_LEASE_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                with self._session_factory() as db:
                    result = db.execute(
                        update(ArchiveJob)
                        .where(
                            ArchiveJob.id == job_id,
                            ArchiveJob.status == "running",
                            ArchiveJob.lease_owner == self.worker_id,
                            ArchiveJob.lease_expires_at > now_text,
                        )
                        .values(lease_expires_at=expires_text, updated_at=now_text)
                    )
                    db.commit()
                    if result.rowcount != 1:
                        lease_lost.set()
                        return
            except Exception as exc:
                logger.warning("archive lease heartbeat failed (%s)", type(exc).__name__)
                lease_lost.set()
                return

    def _assert_owned(self, job_id: str, lease_lost: threading.Event) -> None:
        if lease_lost.is_set():
            raise _LeaseLost("lease heartbeat lost")
        now_text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._session_factory() as db:
            owner = db.execute(
                select(ArchiveJob.id).where(
                    ArchiveJob.id == job_id,
                    ArchiveJob.status == "running",
                    ArchiveJob.lease_owner == self.worker_id,
                    ArchiveJob.lease_expires_at > now_text,
                )
            ).scalar_one_or_none()
        if owner is None:
            lease_lost.set()
            raise _LeaseLost("lease no longer owned")

    def _fenced_checkpoint(
        self,
        db: Session,
        job_id: str,
        *,
        cursor: dict[str, Any] | None = None,
        statistics: dict[str, Any] | None = None,
        status: str | None = None,
        error: str | None = None,
    ) -> None:
        now_text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        values: dict[str, Any] = {"updated_at": now_text}
        if cursor is not None:
            values["cursor_json"] = cursor
        if statistics is not None:
            values["statistics_json"] = statistics
        if status is not None:
            values["status"] = status
            values["error"] = error
            if status in {"completed", "partial", "failed"}:
                values["completed_at"] = now_text
                values["lease_owner"] = None
                values["lease_expires_at"] = None
        elif error is not None:
            values["error"] = error
        result = db.execute(
            update(ArchiveJob)
            .where(
                ArchiveJob.id == job_id,
                ArchiveJob.status == "running",
                ArchiveJob.lease_owner == self.worker_id,
                ArchiveJob.lease_expires_at > now_text,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            raise _LeaseLost("checkpoint rejected by lease fence")

    def _finish_job(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
        cursor: dict[str, Any] | None = None,
        statistics: dict[str, Any] | None = None,
    ) -> bool:
        with self._session_factory() as db:
            try:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                self._fenced_checkpoint(
                    db,
                    job_id,
                    cursor=cursor,
                    statistics=statistics,
                    status=status,
                    error=error,
                )
                db.commit()
                return True
            except _LeaseLost:
                db.rollback()
                return False

    def _requeue_owned_job(self, job_id: str) -> None:
        now_text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with self._session_factory() as db:
                db.execute(
                    update(ArchiveJob)
                    .where(
                        ArchiveJob.id == job_id,
                        ArchiveJob.status == "running",
                        ArchiveJob.lease_owner == self.worker_id,
                    )
                    .values(status="queued", lease_owner=None, lease_expires_at=None, updated_at=now_text)
                )
                db.commit()
        except Exception as exc:
            logger.warning("archive job requeue failed (%s)", type(exc).__name__)

    def _job_state(self, job_id: str, lease_lost: threading.Event) -> tuple[dict[str, Any], dict[str, Any]]:
        self._assert_owned(job_id, lease_lost)
        with self._session_factory() as db:
            job = archive_repo.get_job(db, job_id)
            if job is None:
                raise _LeaseLost("job disappeared")
            return dict(job.cursor or {}), dict(job.statistics or {})

    def _process_scan(self, job_id: str, lease_lost: threading.Event) -> None:
        cursor, stats = self._job_state(job_id, lease_lost)
        with self._session_factory() as db:
            job = archive_repo.get_job(db, job_id)
            if job is None or not job.root_key:
                raise ScanPlanError("scan_job_invalid")
            root_key = job.root_key
            scope = job.relative_directory or ""
            work_by_identity, work_by_path = build_work_indexes(db, root_key)
            work_dirs = work_directories_for_root(work_by_path)

        if not cursor.get("initialized"):
            plan = build_scan_plan(
                root_key,
                scope or None,
                work_directories=work_dirs,
                should_stop=self._stop.is_set,
            )
            cursor = plan.as_cursor()
            cursor["relative_directory"] = scope
            if scope and scope not in cursor["directories"] and not cursor["directories"]:
                # The target may itself be a physical work directory, so leave
                # the empty plan intact and report the bounded unsupported scan.
                cursor["target_was_empty"] = True
            errors = list(cursor.get("enumeration_errors", []))
            stats.setdefault("indexed", 0)
            stats.setdefault("updated", 0)
            stats.setdefault("conflict", 0)
            stats.setdefault("conflicts", int(stats.get("conflict", 0)))
            stats.setdefault("unknown", 0)
            stats.setdefault("failed", 0)
            progress_base = len(cursor.get("unsupported_directories", [])) + len(cursor.get("enumeration_errors", []))
            stats["directories_total"] = len(cursor.get("directories", [])) + progress_base
            stats["directories_scanned"] = progress_base
            cursor["progress_base"] = progress_base
            if cursor.get("unsupported_directories"):
                stats["failed"] += len(cursor["unsupported_directories"])
                errors.extend({"directory": item, "code": "root_level_media_unsupported"} for item in cursor["unsupported_directories"])
            stats["failed"] += len(cursor.get("enumeration_errors", []))
            stats["failed_directories"] = int(stats.get("failed", 0))
            cursor["errors"] = errors
            with self._session_factory() as db:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats)
                db.commit()

        plan = read_scan_plan(root_key, cursor)
        directories = list(plan.directories)
        next_index = int(cursor.get("next_index") or 0)
        attempts = dict(cursor.get("directory_attempts") or {})
        failed_directories = list(cursor.get("failed_directories") or [])
        outcomes = dict(cursor.get("directory_outcomes") or {})
        errors = list(cursor.get("errors") or [])
        progress_base = int(cursor.get("progress_base") or 0)
        stats["directories_total"] = len(directories) + progress_base
        stats.setdefault("directories_scanned", progress_base + next_index)

        while next_index < len(directories):
            if self._stop.is_set():
                return
            self._assert_owned(job_id, lease_lost)
            directory = directories[next_index]
            try:
                with self._session_factory() as db:
                    existing = archive_repo.get_entry_by_path(db, root_key, directory)
                    scanned_fingerprint = entry_content_fingerprint(existing) if existing is not None else None
                result = scan_directory(
                    root_key,
                    directory,
                    plan.evidence_files,
                    existing=existing,
                    work_by_identity=work_by_identity,
                    work_by_path=work_by_path,
                )
            except Exception as exc:
                code = safe_scan_error(exc)
                attempt = int(attempts.get(directory, 0)) + 1
                attempts[directory] = attempt
                if self._stop.is_set():
                    cursor.update({"directory_attempts": attempts, "next_index": next_index})
                    stats["directories_scanned"] = progress_base + next_index
                    with self._session_factory() as db:
                        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                        self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats)
                        db.commit()
                    return
                retryable = isinstance(exc, DirectoryScanError) and exc.retryable
                if retryable and attempt < _MAX_DIRECTORY_ATTEMPTS:
                    cursor.update({"directory_attempts": attempts, "next_index": next_index})
                    stats["directories_scanned"] = progress_base + next_index
                    with self._session_factory() as db:
                        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                        self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats)
                        db.commit()
                    self._stop.wait(min(2 ** (attempt - 1), 4))
                    continue
                stats["failed"] = int(stats.get("failed", 0)) + 1
                stats["failed_directories"] = int(stats["failed"])
                failed_directories.append(directory)
                errors.append({"directory": directory, "code": code})
                outcomes[directory] = "failed"
                next_index += 1
                stats["directories_scanned"] = progress_base + next_index
                cursor.update({
                    "next_index": next_index,
                    "directory_attempts": attempts,
                    "failed_directories": failed_directories,
                    "directory_outcomes": outcomes,
                    "errors": errors,
                })
                with self._session_factory() as db:
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats)
                    db.commit()
                continue

            current_values = result.fields or {}
            editable = {
                key: value for key, value in current_values.items()
                if key not in {"root_key", "relative_directory"}
            }
            if not editable:
                stats["failed"] = int(stats.get("failed", 0)) + 1
                stats["failed_directories"] = int(stats["failed"])
                failed_directories.append(directory)
                errors.append({"directory": directory, "code": result.error_code or "unsupported_platform"})
                outcomes[directory] = "failed"
            else:
                with self._session_factory() as db:
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    existing_now = archive_repo.get_entry_by_path(db, root_key, directory)
                    current_fingerprint = entry_content_fingerprint(existing_now) if existing_now is not None else None
                    if current_fingerprint != scanned_fingerprint:
                        # A concurrent manual correction or scan superseded the
                        # evidence snapshot; never overwrite it with stale fields.
                        stats["failed"] = int(stats.get("failed", 0)) + 1
                        stats["failed_directories"] = int(stats["failed"])
                        failed_directories.append(directory)
                        errors.append({"directory": directory, "code": "archive_entry_changed_during_scan"})
                        outcomes[directory] = "skipped_concurrent_change"
                        next_index += 1
                        stats["directories_scanned"] = progress_base + next_index
                        cursor.update({
                            "next_index": next_index,
                            "directory_attempts": attempts,
                            "failed_directories": failed_directories,
                            "directory_outcomes": outcomes,
                            "errors": errors,
                        })
                        self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats)
                        db.commit()
                        continue
                    old_fingerprint = _entry_fingerprint(existing_now) if existing_now else None
                    editable.pop("sync_status", None)
                    editable.pop("sync_error", None)
                    source_changed = existing_now is None or any(
                        getattr(existing_now, key) != value for key, value in editable.items()
                    )
                    if source_changed:
                        editable["sync_status"] = "pending"
                        editable["sync_error"] = None
                    entry = archive_repo.upsert_entry(
                        db,
                        root_key=root_key,
                        relative_directory=directory,
                        **editable,
                    )
                    new_fingerprint = _entry_fingerprint(entry)
                    changed = source_changed or old_fingerprint != new_fingerprint or entry.sync_status != "ready"
                    outcome = result.outcome
                    outcomes[directory] = outcome
                    if existing_now is None:
                        stats["indexed"] = int(stats.get("indexed", 0)) + 1
                    elif source_changed:
                        stats["updated"] = int(stats.get("updated", 0)) + 1
                    if outcome == "conflict":
                        stats["conflict"] = int(stats.get("conflict", 0)) + 1
                        stats["conflicts"] = int(stats.get("conflicts", 0)) + 1
                    elif outcome == "unknown":
                        stats["unknown"] = int(stats.get("unknown", 0)) + 1
                    if changed:
                        entry.sync_status = "pending"
                        entry.sync_error = None
                        active_sync = db.execute(
                            select(ArchiveJob.id).where(
                                ArchiveJob.job_type == "sync",
                                ArchiveJob.archive_entry_id == entry.id,
                                ArchiveJob.status.in_(("queued", "running")),
                            ).limit(1)
                        ).scalar_one_or_none()
                        if active_sync is None:
                            archive_repo.create_job(
                                db,
                                job_type="sync",
                                root_key=root_key,
                                relative_directory=directory,
                                archive_entry_id=entry.id,
                                cursor={"content_fingerprint": entry_content_fingerprint(entry)},
                                statistics={"attempts": 0, "from_scan": True},
                            )
                    next_index += 1
                    stats["directories_scanned"] = progress_base + next_index
                    cursor.update({
                        "next_index": next_index,
                        "directory_attempts": attempts,
                        "failed_directories": failed_directories,
                        "directory_outcomes": outcomes,
                        "errors": errors,
                    })
                    self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats)
                    db.commit()

            if not editable:
                next_index += 1
                stats["directories_scanned"] = progress_base + next_index
                cursor.update({"next_index": next_index, "directory_outcomes": outcomes, "errors": errors})
                with self._session_factory() as db:
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats)
                    db.commit()

        status = "partial" if stats.get("failed") or plan.truncated else "completed"
        stats["total_directories"] = len(directories) + progress_base
        stats["directories_total"] = len(directories) + progress_base
        stats["directories_scanned"] = len(directories) + progress_base
        stats["truncated"] = bool(plan.truncated)
        stats["failed_directories"] = int(stats.get("failed", 0))
        cursor["next_index"] = len(directories)
        cursor["complete"] = True
        self._finish_job(job_id, status=status, error=None, cursor=cursor, statistics=stats)

    def _process_refresh(self, job_id: str, lease_lost: threading.Event) -> None:
        cursor, stats = self._job_state(job_id, lease_lost)
        with self._session_factory() as db:
            job = archive_repo.get_job(db, job_id)
            entry = db.get(ArchiveEntry, job.archive_entry_id) if job and job.archive_entry_id else None
            if entry is None:
                raise LookupError("archive_entry_missing")
            metadata = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
            if metadata.get("identity_review_required"):
                raise ValueError("archive_identity_review_required")
            if not entry.external_id:
                raise ValueError("archive_identity_missing")
            work = SimpleNamespace(
                platform=entry.platform,
                external_id=entry.external_id,
                title=entry.title,
                url=entry.url,
                published_at=entry.published_at,
            )
            existing_metadata = _resolver_seed(entry)
            original_fingerprint = entry_content_fingerprint(entry)
            entry_id = entry.id

        self._assert_owned(job_id, lease_lost)
        resolution = resolve_archive_metadata(work, existing_metadata=existing_metadata)
        safe_meta = resolution.as_metadata()
        with self._session_factory() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            entry = db.get(ArchiveEntry, entry_id)
            if entry is None:
                raise LookupError("archive_entry_missing")
            if entry_content_fingerprint(entry) != original_fingerprint:
                self._fenced_checkpoint(
                    db,
                    job_id,
                    cursor={**cursor, "superseded": True},
                    statistics=stats,
                    status="failed",
                    error="archive_refresh_superseded",
                )
                db.commit()
                return
            merged_metadata = dict(entry.metadata_json or {})
            new_provenance = safe_meta.pop("provenance", None)
            merged_metadata.update(safe_meta)
            if isinstance(new_provenance, dict):
                prior_provenance = merged_metadata.get("provenance")
                merged_metadata["provenance"] = {
                    **(prior_provenance if isinstance(prior_provenance, dict) else {}),
                    **new_provenance,
                }
            entry.metadata_json = merged_metadata
            if resolution.metadata_checked_at:
                entry.metadata_checked_at = resolution.metadata_checked_at
            if resolution.title.value and resolution.title.verified:
                entry.title = str(resolution.title.value)
            if resolution.published_at.value and resolution.published_at.verified:
                entry.published_at = str(resolution.published_at.value)
                entry.published_time_source = resolution.published_at.source
                entry.published_time_precision = resolution.published_at.precision
                provenance = entry.metadata_json.setdefault("provenance", {})
                if isinstance(provenance, dict):
                    pub_provenance = provenance.setdefault("published_at", {})
                    if isinstance(pub_provenance, dict):
                        pub_provenance.update({
                            "source": resolution.published_at.source,
                            "source_timezone": resolution.published_at.source_timezone,
                            "precision": resolution.published_at.precision,
                            "verified": True,
                            "checked_at": resolution.metadata_checked_at,
                        })
            if resolution.check_status == "verified":
                entry.check_status = "verified"
            elif resolution.check_status == "conflict":
                entry.check_status = "conflict"
            elif entry.check_status != "verified":
                entry.check_status = resolution.check_status
            entry.metadata_json["last_refresh"] = {
                "check_status": resolution.check_status,
                "issues": list(resolution.issues),
                "conflicts": list(resolution.conflicts),
                "checked_at": resolution.metadata_checked_at,
            }
            entry.metadata_json["check_status"] = entry.check_status
            entry.sync_status = "pending"
            entry.sync_error = None
            active_sync = db.execute(
                select(ArchiveJob.id).where(
                    ArchiveJob.job_type == "sync",
                    ArchiveJob.archive_entry_id == entry_id,
                    ArchiveJob.status.in_(("queued", "running")),
                ).limit(1)
            ).scalar_one_or_none()
            if active_sync is None:
                archive_repo.create_job(
                    db,
                    job_type="sync",
                    root_key=entry.root_key,
                    relative_directory=entry.relative_directory,
                    archive_entry_id=entry_id,
                    cursor={"content_fingerprint": entry_content_fingerprint(entry)},
                    statistics={"attempts": 0, "from_refresh": True},
                )
            stats["attempts"] = int(stats.get("attempts", 0)) + 1
            cursor["completed"] = True
            self._fenced_checkpoint(db, job_id, cursor=cursor, statistics=stats, status="completed")
            db.commit()

    def _process_sync(self, job_id: str, lease_lost: threading.Event) -> None:
        cursor, stats = self._job_state(job_id, lease_lost)
        with self._session_factory() as db:
            job = archive_repo.get_job(db, job_id)
            if job is None or job.archive_entry_id is None:
                raise LookupError("archive_entry_missing")
            entry_id = job.archive_entry_id
        self._assert_owned(job_id, lease_lost)
        try:
            sync_archive_entry(entry_id, session_factory=self._session_factory)
        except ArchiveSyncError as exc:
            stats["attempts"] = int(stats.get("attempts", 0)) + 1
            stats["last_error_type"] = type(exc).__name__
            cursor["completed"] = True
            self._finish_job(
                job_id,
                status="failed",
                error="archive_sync_failed",
                cursor=cursor,
                statistics=stats,
            )
            return

        curated_csvs: set[str] = set()
        root_key: str | None = None
        with self._session_factory() as db:
            entry = db.get(ArchiveEntry, entry_id)
            root_key = entry.root_key if entry is not None else None
            metadata = entry.metadata_json if entry is not None else {}
            metadata = metadata if isinstance(metadata, dict) else {}
            source_evidence = metadata.get("source_evidence")
            if entry is not None and entry.check_status != "conflict" and not metadata.get("identity_conflict"):
                for item in source_evidence if isinstance(source_evidence, list) else []:
                    if not isinstance(item, dict):
                        continue
                    relative = item.get("relative_path")
                    if isinstance(relative, str) and Path(relative).name == "合集清单.csv":
                        curated_csvs.add(relative)
        if root_key is None:
            raise LookupError("archive_entry_missing")

        curated_failures = 0
        for relative in sorted(curated_csvs, key=lambda value: (value.casefold(), value)):
            try:
                self._assert_owned(job_id, lease_lost)
                refresh_curated_csv(
                    root_key,
                    relative,
                    entry_id,
                    session_factory=self._session_factory,
                )
            except _LeaseLost:
                raise
            except Exception as exc:
                curated_failures += 1
                logger.warning(
                    "archive curated collection refresh failed job=%s error=%s",
                    job_id,
                    type(exc).__name__,
                )

        stats["attempts"] = int(stats.get("attempts", 0)) + 1
        cursor["completed"] = True
        if curated_failures:
            stats["curated_csv_failures"] = curated_failures
            self._finish_job(
                job_id,
                status="partial",
                error="archive_curated_refresh_failed",
                cursor=cursor,
                statistics=stats,
            )
            return
        self._finish_job(job_id, status="completed", cursor=cursor, statistics=stats)


def _entry_fingerprint(entry: ArchiveEntry | None) -> tuple[Any, ...] | None:
    if entry is None:
        return None
    return (
        entry.work_id,
        entry.platform,
        entry.external_id,
        entry.title,
        entry.url,
        entry.creator_id,
        entry.creator_label,
        entry.group_id,
        entry.group_label,
        entry.published_at,
        entry.published_time_source,
        entry.published_time_precision,
        entry.downloaded_at,
        entry.download_time_source,
        entry.download_time_precision,
        entry.metadata_checked_at,
        entry.check_status,
        entry.metadata_version,
        entry.metadata_json,
        entry.files_json,
    )


def _resolver_seed(entry: ArchiveEntry) -> dict[str, Any]:
    """Combine canonical Entry columns with saved resolver provenance as its seed."""
    metadata = dict(entry.metadata_json or {})
    provenance = metadata.get("provenance")
    publication = provenance.get("published_at") if isinstance(provenance, dict) else None
    publication = publication if isinstance(publication, dict) else {}
    metadata.update({
        "title": entry.title,
        "title_verified": metadata.get("title_verified", entry.check_status == "verified"),
        "published_at": entry.published_at,
        "published_time_source": entry.published_time_source or publication.get("source"),
        "published_time_precision": entry.published_time_precision or publication.get("precision"),
        "published_time_timezone": publication.get("source_timezone", publication.get("timezone")),
        "published_time_verified": publication.get("verified") is True,
        "metadata_checked_at": entry.metadata_checked_at,
        "check_status": entry.check_status,
    })
    return metadata


archive_worker = ArchiveWorker()
