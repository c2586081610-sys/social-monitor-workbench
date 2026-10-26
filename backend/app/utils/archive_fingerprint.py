"""Stable content hashes shared by archive sync and durable job producers."""
from __future__ import annotations

import hashlib
import json
from typing import Any


# Keep aligned with archive_sync_service._CONTENT_FIELDS. Lease state and
# updated_at are intentionally excluded: they do not change sidecar content.
ARCHIVE_SYNC_CONTENT_FIELDS = (
    "root_key", "relative_directory", "work_id", "platform", "external_id", "title", "url",
    "creator_id", "creator_label", "group_id", "group_label", "published_at",
    "published_time_source", "published_time_precision", "downloaded_at", "download_time_source",
    "download_time_precision", "metadata_checked_at", "check_status", "metadata_version",
    "metadata_json", "files_json",
)


def entry_content_fingerprint(entry: Any) -> str:
    """Return an opaque stable hash over the archive fields written to files."""
    values = {key: getattr(entry, key) for key in ARCHIVE_SYNC_CONTENT_FIELDS}
    packed = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()

