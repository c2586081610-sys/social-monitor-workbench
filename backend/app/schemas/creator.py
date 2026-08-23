"""creator schemas（对齐 openapi CreatorCreate/CreatorUpdate/Creator/CreatorDetail/CreatorPage）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Platform
from app.schemas.work import WorkSummary


class CreatorCreate(BaseModel):
    platform: Platform
    name: str = Field(min_length=1, max_length=100)
    profile_url: str = Field(min_length=1)
    external_id: str = Field(min_length=1, max_length=200)
    group_id: int | None = None


class CreatorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    group_id: int | None = None
    enabled: bool | None = None


class Creator(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int | None
    platform: Platform
    name: str
    profile_url: str
    external_id: str
    enabled: bool
    last_poll_at: str | None
    last_work_at: str | None
    created_at: str
    updated_at: str


class CreatorDetail(Creator):
    recent_works: list[WorkSummary] = []


class CreatorPage(BaseModel):
    items: list[Creator]
    total: int
    page: int
    limit: int
    has_more: bool
