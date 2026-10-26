"""Pydantic contract for the path-keyed local archive API."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import Platform


ArchiveCheckStatus = Literal["verified", "needs_review", "conflict", "failed"]
ArchiveSyncStatus = Literal["pending", "ready", "failed"]
ArchiveJobType = Literal["scan", "refresh", "sync"]
ArchiveJobStatus = Literal["queued", "running", "completed", "partial", "failed"]
ArchiveTimeField = Literal["published_at", "downloaded_at"]


class ArchiveFilters(BaseModel):
    """Shared list/export filters; page and limit are ignored by full export."""

    platform: Platform | None = None
    creator_id: int | None = Field(default=None, ge=1)
    group_id: int | None = Field(default=None, ge=1)
    work_id: int | list[int] | None = None
    root_key: str | None = Field(default=None, min_length=1, max_length=32)
    q: str | None = Field(default=None, max_length=200)
    check_status: ArchiveCheckStatus | None = None
    time_field: ArchiveTimeField = "published_at"
    date_from: date | None = None
    date_to: date | None = None
    include_unknown_time: bool = False
    unknown_time_only: bool = False
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def validate_range(self) -> "ArchiveFilters":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        if self.date_to == date.max:
            raise ValueError("date_to is outside the supported range")
        if isinstance(self.work_id, int) and self.work_id < 1:
            raise ValueError("work_id must be positive")
        if isinstance(self.work_id, list) and any(item < 1 for item in self.work_id):
            raise ValueError("work_id values must be positive")
        return self


class ArchiveFile(BaseModel):
    file_id: str = Field(min_length=1, max_length=200)
    relative_path: str = Field(min_length=1, max_length=1000)
    name: str
    size_bytes: int = Field(ge=0)
    media_type: str | None = None
    sha256: str | None = None


class ArchiveEntrySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    root_key: str
    relative_directory: str
    work_id: int | None
    platform: Platform
    external_id: str | None
    title: str
    url: str | None
    creator_id: int | None
    creator_label: str | None
    group_id: int | None
    group_label: str | None
    published_at: str | None
    published_time_source: str | None
    published_time_precision: str | None
    downloaded_at: str | None
    download_time_source: str | None
    download_time_precision: str | None
    metadata_checked_at: str | None
    check_status: ArchiveCheckStatus
    metadata_version: int
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )
    files: list[ArchiveFile] = Field(
        default_factory=list,
        validation_alias=AliasChoices("files_json", "files"),
    )
    sync_status: ArchiveSyncStatus
    sync_error: str | None
    synced_at: str | None
    created_at: str
    updated_at: str


class ArchiveRevisionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archive_entry_id: int
    before_values: dict[str, Any]
    after_values: dict[str, Any]
    source: str
    changed_at: str


class ArchiveEntryDetail(ArchiveEntrySchema):
    revisions: list[ArchiveRevisionSchema] = Field(default_factory=list)


class ArchivePage(BaseModel):
    items: list[ArchiveEntrySchema]
    total: int
    page: int
    limit: int
    has_more: bool


class ArchiveRootPolicy(BaseModel):
    root_key: str
    label: str
    configured: bool


class ArchivePlatformOption(BaseModel):
    value: Platform
    label: str


class ArchivePolicy(BaseModel):
    timezone: Literal["Asia/Shanghai"]
    directory_template: str
    information_files: list[str]
    collection_file_name: str
    catalog_file_name: str
    platforms: list[ArchivePlatformOption]
    roots: list[ArchiveRootPolicy]


class ArchiveJobSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: ArchiveJobType
    status: ArchiveJobStatus
    root_key: str | None
    relative_directory: str | None
    archive_entry_id: int | None
    cursor: dict[str, Any]
    statistics: dict[str, Any]
    error: str | None
    lease_owner: str | None
    lease_expires_at: str | None
    lease_attempts: int
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None


class ArchiveScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_key: str = Field(min_length=1, max_length=32)
    relative_directory: str | None = Field(default=None, max_length=1000)


class ArchiveMetadataPatch(BaseModel):
    """Fields a user may correct; download receipts are intentionally immutable here."""

    model_config = ConfigDict(extra="forbid")

    platform: Platform = None
    external_id: str | None = Field(default=None, max_length=200)
    title: str = Field(default=None, min_length=1, max_length=1000)
    url: str | None = Field(default=None, max_length=2000)
    creator_id: int | None = Field(default=None, ge=1)
    creator_label: str | None = Field(default=None, max_length=500)
    group_id: int | None = Field(default=None, ge=1)
    group_label: str | None = Field(default=None, max_length=500)
    published_at: AwareDatetime | None = None
    published_time_precision: str | None = Field(default=None, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def reject_null_identity_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if not value:
                raise ValueError("at least one metadata field must be provided")
            for key in ("platform", "title"):
                if key in value and value[key] is None:
                    raise ValueError(f"{key} cannot be cleared")
        return value

    @field_validator("published_at", mode="before")
    @classmethod
    def require_published_at_iso_string(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, str):
            raise ValueError("published_at must be an ISO date-time string or null")
        return value

    @field_validator("published_at")
    @classmethod
    def normalize_published_at(cls, value: datetime | None) -> datetime | None:
        """Require an aware ISO date-time and normalize it to UTC; precision stays separate."""
        return value.astimezone(timezone.utc) if value is not None else None
