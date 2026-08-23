"""health schemas（对齐 openapi CookieHealth/SystemHealth）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.common import CookieStatus, Platform


class CookieHealth(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    platform: Platform
    status: CookieStatus
    last_checked_at: str | None
    expires_at: str | None
    note: str | None


class SystemHealth(BaseModel):
    component: str
    status: str  # online / offline / degraded / unknown
    detail: str | None = None
