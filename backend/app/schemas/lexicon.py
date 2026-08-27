"""lexicon schemas（对齐 openapi LexiconCreate/LexiconUpdate/LexiconItem）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import LexiconAction


class LexiconCreate(BaseModel):
    term: str = Field(min_length=1, max_length=50)
    action: LexiconAction = "increase"
    weight: float = Field(default=1.0, ge=0.0)
    enabled: bool = True
    platform_scope: str | None = None
    category: str | None = None  # 兴趣区间：finance/ai/fitness/business/general


class LexiconUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=50)
    action: LexiconAction | None = None
    weight: float | None = Field(default=None, ge=0.0)
    enabled: bool | None = None
    platform_scope: str | None = None
    category: str | None = None


class LexiconItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    term: str
    action: LexiconAction
    weight: float
    enabled: bool
    platform_scope: str | None
    category: str | None
    created_at: str
    updated_at: str
