"""wechat schemas（对齐 openapi WechatImportRequest，预留占位）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class WechatImportRequest(BaseModel):
    url: str = Field(min_length=1)
    title: str | None = None
