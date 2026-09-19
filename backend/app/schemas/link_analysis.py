"""手动链接分析 API 的输入输出契约。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.work import Work


LinkPlatform = Literal["douyin", "bilibili", "xhs", "twitter"]
LinkAnalysisMode = Literal["one_time", "monitor"]


class LinkAnalysisCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    platform: LinkPlatform
    external_id: str = Field(min_length=1, max_length=200)
    mode: LinkAnalysisMode = "one_time"


class LinkAnalysisResult(BaseModel):
    work: Work
    created: bool
    mode: LinkAnalysisMode


class NoteCompletionRequest(BaseModel):
    note_path: str = Field(min_length=1, max_length=500)
