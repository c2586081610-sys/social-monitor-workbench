"""Select Bilibili works by CLI parameters; checkpoint, then transcribe only.

This portable one-off runner deliberately does not extract frames, generate
notes, or use a personal creator/work selection. The shared jobs helper commits
the download receipt and pending ArchiveEntry sync job before transcription.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from monitor.store.shared_db import SessionLocal, init_db  # noqa: E402
from app.models import Work  # noqa: E402
from app.repositories import task_repo  # noqa: E402
from app.utils.archive_paths import relative_path_from_root  # noqa: E402
from monitor import jobs  # noqa: E402
from monitor.pipeline import transcribe  # noqa: E402
from monitor.pipeline.download import PipelineOfflineError  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-id", type=int, required=True, help="local Creator row ID")
    parser.add_argument("--min-work-id", type=int, default=0, help="include Work rows above this ID")
    parser.add_argument(
        "--status",
        choices=("QUEUED", "FAILED"),
        default="QUEUED",
        help="select one retryable Work status (default: QUEUED)",
    )
    return parser


def _safe_error(exc: Exception, *, stage: str) -> str:
    if isinstance(exc, PipelineOfflineError):
        return str(exc)
    return f"{stage} failed ({type(exc).__name__})"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("bili_download_transcribe")
    init_db()

    with SessionLocal() as db:
        work_ids = list(db.execute(
            select(Work.id)
            .where(
                Work.platform == "bilibili",
                Work.content_type == "video",
                Work.creator_id == args.creator_id,
                Work.id > args.min_work_id,
                Work.status == args.status,
            )
            .order_by(Work.id)
        ).scalars())
    logger.info("selected=%s", len(work_ids))

    succeeded = failed = 0
    for work_id in work_ids:
        with SessionLocal() as db:
            work = db.get(Work, work_id)
            if work is None or work.status != args.status:
                continue
            try:
                checkpoint = jobs.download_and_checkpoint(db, work)
                video_file = next(
                    (item for item in checkpoint.result.files if item.media_type == "video"),
                    checkpoint.result.files[0],
                )
                work.status = "TRANSCRIBING"
                prior = task_repo.get_by_work_stage(db, work.id, "transcribe")
                attempts = (prior.attempts if prior is not None else 0) + 1
                task = task_repo.upsert(db, work.id, "transcribe", "running", attempts=attempts)
                task.error = None
                db.commit()

                transcript_path = transcribe.transcribe(
                    str(video_file.path),
                    checkpoint.media_dir / "transcript",
                )
                work.transcript_path = relative_path_from_root("media", str(transcript_path))
                task_repo.upsert(db, work.id, "transcribe", "succeeded", attempts=attempts)
                work.status = "DONE"
                work.last_error = None
                db.commit()
                succeeded += 1
                logger.info("done work_id=%s", work_id)
            except Exception as exc:  # noqa: BLE001 - batch row failures do not stop later rows
                stage = "transcribe" if work.status == "TRANSCRIBING" else "download"
                safe_error = _safe_error(exc, stage=stage)
                work.status = "FAILED"
                work.last_error = safe_error
                task_repo.mark_failed(db, work.id, stage, safe_error)
                db.commit()
                failed += 1
                logger.warning("failed work_id=%s stage=%s error_type=%s", work_id, stage, type(exc).__name__)

    logger.info("finished succeeded=%s failed=%s", succeeded, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
