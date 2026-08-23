"""tag schemas（对齐 openapi Tag）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.common import TagKind


class Tag(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: TagKind
    work_count: int = 0
