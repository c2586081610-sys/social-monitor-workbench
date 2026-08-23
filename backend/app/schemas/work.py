"""work schemas（对齐 openapi Work/WorkSummary/WorkDetail/WorkPage/TaskStage/Frame/ClassifyRequest）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import SourceType, WorkStatus


class WorkSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: WorkStatus
    published_at: str | None


class Work(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    creator_id: int | None
    group_id: int | None
    platform: str
    external_id: str
    title: str
    url: str
    published_at: str | None
    source_type: SourceType
    status: WorkStatus
    task_id: str | None
    media_path: str | None
    note_path: str | None
    frame_count: int = 0
    retry_count: int = 0
    last_error: str | None
    created_at: str
    updated_at: str


class TaskStage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    status: str
    attempts: int
    error: str | None


class Frame(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file: str
    time_seconds: float
    window_start: float | None = None
    window_end: float | None = None
    hits: list[dict] = []
    confidence: float = 0.0


class WorkDetail(Work):
    tags: list[dict] = []
    stages: list[TaskStage] = []
    transcript_path: str | None = None
    frame_manifest_path: str | None = None


class WorkPage(BaseModel):
    items: list[Work]
    total: int
    page: int
    limit: int
    has_more: bool


class ClassifyRequest(BaseModel):
    group_id: int = Field(ge=1)
    tags: list[str] = Field(default_factory=list, max_length=20)
    creator_id: int | None = None
