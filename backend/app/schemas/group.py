"""group schemas（对齐 openapi GroupCreate/GroupUpdate/Group）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class GroupUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class Group(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    creator_count: int = 0
    created_at: str
    updated_at: str
