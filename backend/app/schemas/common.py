"""公共类型：平台/作品状态等（对齐 openapi-aggregator.yaml schemas）。"""
from __future__ import annotations

from typing import Literal

Platform = Literal["douyin", "bilibili", "xhs", "twitter", "wechat"]
WorkStatus = Literal[
    "NEW",
    "QUEUED",
    "DOWNLOADING",
    "TRANSCRIBING",
    "FRAME_EXTRACTING",
    "NOTE_GENERATING",
    "DONE",
    "FAILED",
    "UNCLASSIFIED",
]
SourceType = Literal["monitor", "like", "favorite", "manual"]
TagKind = Literal["big", "small"]
LexiconAction = Literal["increase", "decrease"]
CookieStatus = Literal["OK", "WARN", "NEEDS_RELOGIN", "UNKNOWN"]
StageName = Literal["parse", "download", "transcribe", "frames", "note"]
StageStatus = Literal["pending", "running", "succeeded", "failed"]

WORK_STATUSES: tuple[str, ...] = (
    "NEW",
    "QUEUED",
    "DOWNLOADING",
    "TRANSCRIBING",
    "FRAME_EXTRACTING",
    "NOTE_GENERATING",
    "DONE",
    "FAILED",
    "UNCLASSIFIED",
)
