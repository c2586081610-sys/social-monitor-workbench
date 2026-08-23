"""tasks（阶段级任务）数据访问：UNIQUE(work_id, stage) 幂等 upsert。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task


def get(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)


def get_by_work_stage(db: Session, work_id: int, stage: str) -> Task | None:
    return db.execute(
        select(Task).where(Task.work_id == work_id, Task.stage == stage)
    ).scalar_one_or_none()


def list_by_work(db: Session, work_id: int) -> list[Task]:
    stmt = (
        select(Task)
        .where(Task.work_id == work_id)
        .order_by(Task.id)
    )
    return list(db.execute(stmt).scalars().all())


def upsert(db: Session, work_id: int, stage: str, status: str, error: str | None = None, attempts: int | None = None) -> Task:
    task = get_by_work_stage(db, work_id, stage)
    if task is None:
        task = Task(work_id=work_id, stage=stage, status=status)
        db.add(task)
    task.status = status
    if error is not None:
        task.error = error
    if attempts is not None:
        task.attempts = attempts
    db.flush()
    return task


def mark_failed(db: Session, work_id: int, stage: str, error: str) -> Task:
    return upsert(db, work_id, stage, "failed", error=error)


def increment_attempts(db: Session, work_id: int, stage: str) -> Task:
    task = get_by_work_stage(db, work_id, stage)
    if task is None:
        task = Task(work_id=work_id, stage=stage, status="pending")
        db.add(task)
    task.attempts += 1
    db.flush()
    return task
