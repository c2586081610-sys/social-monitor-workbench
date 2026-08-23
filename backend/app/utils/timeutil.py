"""时间工具：统一 ISO-8601 UTC 字符串存储。"""
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """当前 UTC 时间，ISO-8601 格式。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def to_date(value: str | None) -> str | None:
    """取日期部分 YYYY-MM-DD；无法解析返回 None。"""
    dt = parse_iso(value)
    return dt.strftime("%Y-%m-%d") if dt else None
