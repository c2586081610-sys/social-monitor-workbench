"""Bounded platform metadata lookups for new and historical archive records.

The resolver consumes validated collector payloads for the platforms that
already expose them and uses bounded fixed-host Bilibili detail and WBI list
adapters. It never fetches a caller-provided URL. Existing values are retained
on missing, conflicting, offline, or risk-controlled responses.
"""
from __future__ import annotations

import hashlib
import html
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx


_BILIBILI_VIEW_ENDPOINT = "https://api.bilibili.com/x/web-interface/view"
_BILIBILI_NAV_ENDPOINT = "https://api.bilibili.com/x/web-interface/nav"
_BILIBILI_FINGER_ENDPOINT = "https://api.bilibili.com/x/frontend/finger/spi"
_BILIBILI_SPACE_WBI_ENDPOINT = "https://api.bilibili.com/x/space/wbi/arc/search"
_WBI_MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
)
_BVID_RE = re.compile(r"^BV[0-9A-Za-z]{10}$")
_AVID_RE = re.compile(r"^av[1-9][0-9]{0,18}$", re.IGNORECASE)
_COLLECTOR_SOURCE = {
    "bilibili": "bilibili_rsshub_collector",
    "douyin": "douyin_mediacrawler_collector",
    "xhs": "xhs_mediacrawler_collector",
    "twitter": "twitter_rsshub_collector",
}
_COLLECTOR_HOSTS = {
    "bilibili": {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"},
    "douyin": {"douyin.com", "www.douyin.com", "iesdouyin.com", "www.iesdouyin.com", "v.douyin.com"},
    "xhs": {"xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com"},
    "twitter": {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "t.co"},
}

PublicationPrecision = Literal["day", "minute", "second"]
ArchiveCheckStatus = Literal["verified", "needs_review", "conflict", "failed"]


@dataclass(frozen=True)
class ResolvedField:
    """One value and its field-level provenance; verified is never inferred from shape."""

    value: str | int | None
    source: str | None = None
    precision: PublicationPrecision | None = None
    verified: bool = False
    source_timezone: str | None = None


@dataclass(frozen=True)
class MetadataConflict:
    field: str
    retained: ResolvedField
    incoming: ResolvedField


@dataclass(frozen=True)
class ArchiveMetadataResolution:
    platform: str
    external_id: str
    title: ResolvedField
    published_at: ResolvedField
    owner_id: ResolvedField
    owner_name: ResolvedField
    duration_seconds: ResolvedField
    metadata_checked_at: str | None
    check_status: ArchiveCheckStatus
    issues: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    conflict_evidence: tuple[MetadataConflict, ...] = ()

    def publication_provenance(self) -> dict[str, Any] | None:
        """Shape consumed by ``make_work_directory_name`` when creating a new path."""
        field = self.published_at
        if not field.verified or not field.value or not field.source or not field.precision:
            return None
        source_timezone = field.source_timezone
        if field.precision in {"day", "minute"} and not source_timezone:
            return None
        if source_timezone and _source_timezone_value(source_timezone) is None:
            return None
        source_timezone = source_timezone or "UTC"
        return {
            "verified": True,
            "value": str(field.value),
            "source": field.source,
            "precision": field.precision,
            "timezone": source_timezone,
            "source_timezone": source_timezone,
            "checked_at": self.metadata_checked_at,
            "check_status": self.check_status,
        }

    def as_metadata(self) -> dict[str, Any]:
        """Return a path-free shape suitable for the archive metadata JSON column."""
        result = {
            "title": self.title.value,
            "title_source": self.title.source,
            "owner_id": self.owner_id.value,
            "owner_id_source": self.owner_id.source,
            "owner_name": self.owner_name.value,
            "owner_name_source": self.owner_name.source,
            "duration_seconds": self.duration_seconds.value,
            "duration_source": self.duration_seconds.source,
            "published_at": self.published_at.value,
            "published_time_source": self.published_at.source,
            "published_time_precision": self.published_at.precision,
            "published_time_timezone": self.published_at.source_timezone,
            "published_time_verified": self.published_at.verified,
            "metadata_checked_at": self.metadata_checked_at,
            "check_status": self.check_status,
            "issues": list(self.issues),
            "conflicts": list(self.conflicts),
            "conflict_evidence": [
                {
                    "field": item.field,
                    "retained": _field_metadata(item.retained),
                    "incoming": _field_metadata(item.incoming),
                }
                for item in self.conflict_evidence
            ],
        }
        publication = self.publication_provenance()
        if publication is not None:
            result["provenance"] = {"published_at": publication}
        return result


def _field_metadata(field: ResolvedField) -> dict[str, Any]:
    return {
        "value": field.value,
        "source": field.source,
        "precision": field.precision,
        "verified": field.verified,
        "source_timezone": field.source_timezone,
    }


@dataclass(frozen=True)
class BilibiliCandidate:
    bvid: str
    title: str
    owner_id: str | None
    owner_id_source: str | None
    owner_name: str | None
    owner_name_source: str | None
    duration_seconds: int | None
    duration_source: str | None
    published_at: str | None
    publication_source: str | None
    publication_precision: PublicationPrecision | None
    source_timezone: str | None = "UTC"
    source: str = "bilibili_space_wbi_arc_search"


@dataclass(frozen=True)
class BilibiliCandidateDiscovery:
    owner_id: str
    candidates: tuple[BilibiliCandidate, ...]
    pages_fetched: int
    max_pages: int
    complete: bool
    truncated: bool
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class BilibiliCandidateVerification:
    bvid: str
    verified: bool
    detail_title: str | None
    owner_id: str | None
    owner_name: str | None
    duration_seconds: int | None
    published_at: str | None
    publication_source: str | None
    publication_precision: PublicationPrecision | None
    source_timezone: str | None
    metadata_checked_at: str | None
    issues: tuple[str, ...] = ()


class BilibiliLookupError(RuntimeError):
    """A bounded Bilibili request failed; ``category`` is safe for UI/reporting."""

    def __init__(self, category: str, *, pages_fetched: int = 0) -> None:
        self.category = category
        self.pages_fetched = pages_fetched
        if category == "risk_control":
            message = "Bilibili blocked or rate-limited the metadata request"
        elif category == "network":
            message = "Bilibili metadata request failed at the network layer"
        elif category == "malformed":
            message = "Bilibili returned an incomplete metadata response"
        else:
            message = "Bilibili metadata request failed"
        super().__init__(message)


_RISK_CONTROL_CODES = {-352, -412, -509, -799}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source_timezone_value(label: str) -> tzinfo | None:
    if label == "UTC":
        return timezone.utc
    if re.fullmatch(r"UTC[+-]\d{2}:\d{2}", label):
        sign = 1 if label[3] == "+" else -1
        hours = int(label[4:6])
        minutes = int(label[7:9])
        if hours > 23 or minutes > 59:
            return None
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    try:
        return ZoneInfo(label)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _datetime_value(value: Any, timezone_hint: str | None = None) -> tuple[str, PublicationPrecision, str] | None:
    """Normalize an aware ISO timestamp without adding missing precision."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    is_date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw))
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    source_timezone = timezone_hint
    if source_timezone:
        source_zone = _source_timezone_value(source_timezone)
        if source_zone is None:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if not timezone_hint:
            return None
        try:
            parsed = parsed.replace(tzinfo=_source_timezone_value(timezone_hint))
        except (ZoneInfoNotFoundError, ValueError):
            return None
    if source_timezone is None:
        offset = parsed.utcoffset()
        if offset is None or offset.total_seconds() % 60:
            return None
        offset_minutes = int(offset.total_seconds() // 60)
        if offset_minutes == 0:
            source_timezone = "UTC"
        else:
            sign = "+" if offset_minutes > 0 else "-"
            hours, minutes = divmod(abs(offset_minutes), 60)
            source_timezone = f"UTC{sign}{hours:02d}:{minutes:02d}"
    date_time = re.split(r"[Tt]", raw, maxsplit=1)
    if is_date_only or len(date_time) == 1:
        precision: PublicationPrecision = "day"
    else:
        time_text = date_time[1]
        clock_text = re.split(r"[+-]|Z$", time_text, maxsplit=1)[0]
        if "." in clock_text:
            precision = "second"
        else:
            pieces = clock_text.split(":")
            precision = "second" if len(pieces) >= 3 else "minute"
    normalized = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds" if parsed.microsecond else "seconds")
    normalized = normalized.replace("+00:00", "Z")
    # Keep source-local midnight's actual UTC instant (e.g. Shanghai's
    # 2026-10-01 00:00 is 2026-09-30T16:00Z). A date-only value remains a
    # day-precision instant at that source day's start, never UTC midnight.
    if precision == "minute":
        normalized = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
    return normalized, precision, source_timezone


def _timestamp_seconds(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        timestamp = int(value)
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _duration_seconds(value: Any) -> int | None:
    """Parse an API duration in seconds or the platform's H:MM:SS / M:SS form."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.isdigit():
        parsed = int(raw)
        return parsed if parsed > 0 else None
    parts = raw.split(":")
    if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60):
        return None
    seconds = numbers[0] * 60 + numbers[1] if len(numbers) == 2 else numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return seconds if seconds > 0 else None


def _work_value(work: Any, key: str, default=None):
    if isinstance(work, Mapping):
        return work.get(key, default)
    return getattr(work, key, default)


def _validated_platform_id(platform: str, external_id: str) -> bool:
    if platform == "bilibili":
        return bool(_BVID_RE.fullmatch(external_id) or _AVID_RE.fullmatch(external_id))
    if platform == "douyin":
        return bool(re.fullmatch(r"[0-9]{8,30}", external_id))
    if platform == "xhs":
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{6,128}", external_id))
    if platform == "twitter":
        return bool(re.fullmatch(r"[0-9]{5,25}", external_id))
    return False


def _url_identity(url: str) -> tuple[str | None, str | None, bool]:
    """Return (platform, ID, recognized_host); never resolves redirects."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 80, 443)
        ):
            return None, None, False
    except (TypeError, ValueError):
        return None, None, False
    for platform, hosts in _COLLECTOR_HOSTS.items():
        if host not in hosts:
            continue
        path = parsed.path
        match = None
        if platform == "bilibili":
            match = re.search(r"(?:^|/)video/(BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,18})(?:/|$)", path, re.IGNORECASE)
        elif platform == "douyin":
            match = re.search(r"/(?:video|share/video)/([0-9]{8,30})(?:/|$)", path)
        elif platform == "xhs":
            match = re.search(r"/(?:explore|discovery/item)/([A-Za-z0-9_-]{6,128})(?:/|$)", path)
        elif platform == "twitter":
            match = re.search(r"/status/([0-9]{5,25})(?:/|$)", path)
        return platform, match.group(1) if match else None, True
    return None, None, False


def _identity_error(platform: str, external_id: str, url: str | None) -> str | None:
    if not _validated_platform_id(platform, external_id):
        return "unsupported_or_invalid_platform_identity"
    if not url:
        return None
    url_platform, url_id, recognized = _url_identity(url)
    if not recognized or url_platform != platform:
        return "platform_url_host_mismatch"
    # Known short-link hosts have no stable ID in their visible path. They are
    # accepted as platform hints only; the fixed-platform detail response must
    # still verify the requested ID before any metadata is selected.
    if url_id is not None and url_id != external_id:
        return "platform_url_identity_mismatch"
    return None


def _field_from_existing(
    value: Any,
    source: Any,
    *,
    precision: Any = None,
    verified: Any = False,
    source_timezone: Any = None,
) -> ResolvedField:
    source_value = str(source).strip() if isinstance(source, str) and source.strip() else None
    valid_precision = precision if isinstance(precision, str) and precision in {"day", "minute", "second"} else None
    return ResolvedField(
        value=value if isinstance(value, (str, int)) and not isinstance(value, bool) else None,
        source=source_value,
        precision=valid_precision,
        verified=bool(verified is True and source_value),
        source_timezone=(source_timezone.strip() if isinstance(source_timezone, str) and source_timezone.strip() else None),
    )


def _existing_seed(work: Any, existing: Mapping[str, Any] | None) -> tuple[ResolvedField, ...]:
    stored = existing or {}
    provenance = stored.get("provenance")
    publication_provenance = provenance.get("published_at") if isinstance(provenance, Mapping) else None
    provenance_timezone = None
    if isinstance(publication_provenance, Mapping):
        provenance_timezone = publication_provenance.get("source_timezone", publication_provenance.get("timezone"))
    title = _field_from_existing(
        stored.get("title", _work_value(work, "title")),
        stored.get("title_source"),
        verified=stored.get("title_verified", False),
    )
    published = _field_from_existing(
        stored.get("published_at", _work_value(work, "published_at")),
        stored.get("published_time_source", stored.get("publication_source")),
        precision=stored.get("published_time_precision", stored.get("publication_precision")),
        verified=stored.get("published_time_verified", False),
        source_timezone=stored.get("published_time_timezone", stored.get("publication_timezone", provenance_timezone)),
    )
    owner = _work_value(work, "creator")
    db_owner_id = getattr(owner, "external_id", None) if owner is not None else None
    db_owner_name = getattr(owner, "name", None) if owner is not None else None
    owner_id = _field_from_existing(
        stored.get("owner_id", db_owner_id),
        stored.get("owner_id_source", "work_creator" if db_owner_id else None),
        verified=stored.get("owner_id_verified", False),
    )
    owner_name = _field_from_existing(
        stored.get("owner_name", db_owner_name),
        stored.get("owner_name_source", "work_creator" if db_owner_name else None),
        verified=stored.get("owner_name_verified", False),
    )
    duration = _field_from_existing(
        stored.get("duration_seconds"),
        stored.get("duration_source"),
        verified=stored.get("duration_verified", False),
    )
    return title, published, owner_id, owner_name, duration


def _existing_conflicts(
    existing: Mapping[str, Any] | None,
) -> tuple[list[str], list[MetadataConflict]]:
    if not isinstance(existing, Mapping):
        return [], []
    raw_conflicts = existing.get("conflicts")
    conflicts = list(dict.fromkeys(
        item for item in raw_conflicts if isinstance(item, str) and item
    )) if isinstance(raw_conflicts, (list, tuple)) else []
    evidence: list[MetadataConflict] = []
    raw_evidence = existing.get("conflict_evidence")
    if not isinstance(raw_evidence, (list, tuple)):
        return conflicts, evidence
    for item in raw_evidence:
        if not isinstance(item, Mapping) or not isinstance(item.get("field"), str):
            continue
        retained = item.get("retained")
        incoming = item.get("incoming")
        if not isinstance(retained, Mapping) or not isinstance(incoming, Mapping):
            continue
        evidence.append(
            MetadataConflict(
                item["field"],
                _field_from_existing(
                    retained.get("value"),
                    retained.get("source"),
                    precision=retained.get("precision"),
                    verified=retained.get("verified"),
                    source_timezone=retained.get("source_timezone"),
                ),
                _field_from_existing(
                    incoming.get("value"),
                    incoming.get("source"),
                    precision=incoming.get("precision"),
                    verified=incoming.get("verified"),
                    source_timezone=incoming.get("source_timezone"),
                ),
            )
        )
    return conflicts, evidence


def _collector_payload(source_context: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(source_context, Mapping):
        return None
    payload = source_context.get("payload")
    return payload if isinstance(payload, Mapping) else source_context


def _collector_context_matches(
    platform: str, external_id: str, url: str | None, source_context: Mapping[str, Any] | None
) -> bool:
    if not isinstance(source_context, Mapping):
        return False
    payload = _collector_payload(source_context)
    if payload is None:
        return False
    for values in (source_context, payload):
        context_platform = values.get("platform")
        context_id = values.get("external_id")
        if context_platform is not None and context_platform != platform:
            return False
        if context_id is not None and str(context_id) != external_id:
            return False
        context_url = values.get("url")
        if isinstance(context_url, str) and context_url:
            context_platform_from_url, context_id_from_url, recognized = _url_identity(context_url)
            if not recognized or context_platform_from_url != platform:
                return False
            if context_id_from_url is not None and context_id_from_url != external_id:
                return False
    if payload.get("platform") is None or payload.get("external_id") is None:
        return False
    return True


def _collector_field_values(platform: str, source_context: Mapping[str, Any]) -> dict[str, ResolvedField]:
    payload = _collector_payload(source_context)
    if payload is None:
        return {}
    source = _COLLECTOR_SOURCE.get(platform)
    if not source:
        return {}
    values: dict[str, ResolvedField] = {}
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        values["title"] = ResolvedField(title.strip(), source, None, True)
    timezone_hint = payload.get("published_timezone", source_context.get("timezone"))
    if not isinstance(timezone_hint, str):
        timezone_hint = None
    publication = _datetime_value(payload.get("published_at"), timezone_hint)
    if publication is not None:
        normalized, precision, source_timezone = publication
        values["published_at"] = ResolvedField(normalized, source, precision, True, source_timezone)
    owner_id = payload.get("owner_id", payload.get("mid", payload.get("author_id")))
    if isinstance(owner_id, (str, int)) and not isinstance(owner_id, bool) and str(owner_id).strip():
        values["owner_id"] = ResolvedField(str(owner_id).strip(), source, None, True)
    owner_name = payload.get("owner_name", payload.get("owner", payload.get("author")))
    if isinstance(owner_name, Mapping):
        owner_name = owner_name.get("name")
    if isinstance(owner_name, str) and owner_name.strip():
        values["owner_name"] = ResolvedField(owner_name.strip(), source, None, True)
    duration = _duration_seconds(payload.get("duration_seconds", payload.get("duration")))
    if duration is not None:
        values["duration_seconds"] = ResolvedField(duration, source, None, True)
    return values


def _same_value(left: ResolvedField, right: ResolvedField) -> bool:
    if left.value is None or right.value is None:
        return False
    if isinstance(left.value, str) and isinstance(right.value, str):
        return left.value == right.value
    return left.value == right.value


_PRECISION_RANK = {"day": 0, "minute": 1, "second": 2}


def _publication_interval(field: ResolvedField) -> tuple[datetime, datetime] | None:
    if not isinstance(field.value, str) or field.precision not in _PRECISION_RANK:
        return None
    try:
        value = datetime.fromisoformat(field.value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    source_timezone = field.source_timezone or ("UTC" if field.precision == "second" else None)
    if source_timezone is None:
        return None
    source_zone = _source_timezone_value(source_timezone)
    if source_zone is None:
        return None
    local = value.astimezone(source_zone)
    start = local.astimezone(timezone.utc)
    if field.precision == "day":
        local_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)
    elif field.precision == "minute":
        local_start = local.replace(second=0, microsecond=0)
        return local_start.astimezone(timezone.utc), (local_start + timedelta(minutes=1)).astimezone(timezone.utc)
    else:
        local_start = local.replace(microsecond=0)
        return local_start.astimezone(timezone.utc), (local_start + timedelta(seconds=1)).astimezone(timezone.utc)


def _publication_values_compatible(left: ResolvedField, right: ResolvedField) -> bool:
    left_interval = _publication_interval(left)
    right_interval = _publication_interval(right)
    if left_interval is None or right_interval is None:
        return _same_value(left, right)
    return left_interval[0] < right_interval[1] and right_interval[0] < left_interval[1]


def _record_conflict(
    field_name: str,
    retained: ResolvedField,
    incoming: ResolvedField,
    conflicts: list[str],
    evidence: list[MetadataConflict],
) -> None:
    if field_name not in conflicts:
        conflicts.append(field_name)
    pair = MetadataConflict(field_name, retained, incoming)
    if pair not in evidence:
        evidence.append(pair)


def _merge_verified_field(
    current: ResolvedField,
    incoming: ResolvedField,
    field_name: str,
    conflicts: list[str],
    evidence: list[MetadataConflict],
) -> ResolvedField:
    if incoming.value is None:
        return current
    if (
        field_name == "owner_id"
        and current.value is not None
        and current.source == "work_creator"
        and str(current.value) != str(incoming.value)
    ):
        _record_conflict(field_name, current, incoming, conflicts, evidence)
        return current
    if current.value is None or not current.verified:
        return incoming

    compatible = (
        _publication_values_compatible(current, incoming)
        if field_name == "published_at"
        else _same_value(current, incoming)
    )
    if not compatible:
        _record_conflict(field_name, current, incoming, conflicts, evidence)
        return current

    if field_name == "published_at":
        current_rank = _PRECISION_RANK.get(current.precision or "", -1)
        incoming_rank = _PRECISION_RANK.get(incoming.precision or "", -1)
        if incoming_rank > current_rank:
            return incoming
    return current


def _merge_preserving(
    current: ResolvedField,
    incoming: ResolvedField,
    field_name: str,
    conflicts: list[str],
    evidence: list[MetadataConflict],
) -> ResolvedField:
    return _merge_verified_field(current, incoming, field_name, conflicts, evidence)


def _merge_bilibili_detail(
    current: dict[str, ResolvedField],
    detail: Mapping[str, Any],
    conflicts: list[str],
    evidence: list[MetadataConflict],
) -> None:
    detail_title = detail.get("title")
    owner = detail.get("owner") if isinstance(detail.get("owner"), Mapping) else {}
    source = "bilibili_view_api"
    if isinstance(detail_title, str) and detail_title.strip():
        incoming = ResolvedField(detail_title.strip(), source, None, True)
        current["title"] = _merge_verified_field(current["title"], incoming, "title", conflicts, evidence)

    pubdate = _timestamp_seconds(detail.get("pubdate"))
    if pubdate:
        incoming = ResolvedField(pubdate, source, "second", True, "UTC")
        current["published_at"] = _merge_verified_field(
            current["published_at"], incoming, "published_at", conflicts, evidence
        )

    owner_id = owner.get("mid")
    if isinstance(owner_id, (str, int)) and str(owner_id).isdigit() and int(owner_id) > 0:
        incoming = ResolvedField(str(owner_id), source, None, True)
        current["owner_id"] = _merge_verified_field(
            current["owner_id"], incoming, "owner_id", conflicts, evidence
        )
    owner_name = owner.get("name")
    if isinstance(owner_name, str) and owner_name.strip():
        incoming = ResolvedField(owner_name.strip(), source, None, True)
        current["owner_name"] = _merge_verified_field(
            current["owner_name"], incoming, "owner_name", conflicts, evidence
        )

    duration = _duration_seconds(detail.get("duration"))
    if duration is not None:
        incoming = ResolvedField(duration, source, None, True)
        current["duration_seconds"] = _merge_verified_field(
            current["duration_seconds"], incoming, "duration_seconds", conflicts, evidence
        )


def _bilibili_request_id(external_id: str) -> dict[str, str | int]:
    if _BVID_RE.fullmatch(external_id):
        return {"bvid": external_id}
    if _AVID_RE.fullmatch(external_id):
        return {"aid": int(external_id[2:])}
    raise ValueError("invalid Bilibili work ID")


def _fetch_bilibili_json(
    endpoint: str,
    params: Mapping[str, Any],
    timeout: float,
    *,
    cookies: Mapping[str, str] | None = None,
    allow_auth_required_nav: bool = False,
) -> Mapping[str, Any]:
    """GET one of the module's constant Bilibili endpoints; caller URLs are never accepted."""
    if endpoint not in {
        _BILIBILI_VIEW_ENDPOINT,
        _BILIBILI_NAV_ENDPOINT,
        _BILIBILI_FINGER_ENDPOINT,
        _BILIBILI_SPACE_WBI_ENDPOINT,
    }:
        raise ValueError("unsupported Bilibili endpoint")
    try:
        response = httpx.get(
            endpoint,
            params=dict(params),
            cookies=dict(cookies or {}),
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
            },
        )
    except httpx.HTTPError as exc:
        raise BilibiliLookupError("network") from exc
    if response.status_code == 429:
        raise BilibiliLookupError("risk_control")
    if response.status_code >= 500:
        raise BilibiliLookupError("network")
    if response.status_code != 200:
        raise BilibiliLookupError("http")
    try:
        payload = response.json()
    except (ValueError, TypeError):
        raise BilibiliLookupError("malformed") from None
    if not isinstance(payload, Mapping):
        raise BilibiliLookupError("malformed")
    code = payload.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        raise BilibiliLookupError("malformed")
    nav_anonymous_key_response = (
        endpoint == _BILIBILI_NAV_ENDPOINT
        and allow_auth_required_nav
        and code == -101
    )
    if code != 0 and not nav_anonymous_key_response:
        raise BilibiliLookupError("risk_control" if code in _RISK_CONTROL_CODES else "http")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise BilibiliLookupError("malformed")
    return data


def _wbi_asset_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host.endswith(".hdslb.com"):
        return None
    filename = parsed.path.rsplit("/", 1)[-1]
    match = re.fullmatch(r"([A-Za-z0-9]{32})\.(?:png|jpg|jpeg|webp)", filename, re.IGNORECASE)
    return match.group(1) if match else None


def _bilibili_wbi_material(timeout: float) -> tuple[str, str, dict[str, str]]:
    """Load one anonymous Bilibili fingerprint and the current signed-key pair."""
    fingerprint = _fetch_bilibili_json(_BILIBILI_FINGER_ENDPOINT, {}, timeout)
    buvid3 = fingerprint.get("b_3")
    buvid4 = fingerprint.get("b_4")
    safe_cookie_value = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
    if not isinstance(buvid3, str) or not safe_cookie_value.fullmatch(buvid3):
        raise BilibiliLookupError("malformed")
    cookies = {"buvid3": buvid3}
    if isinstance(buvid4, str) and safe_cookie_value.fullmatch(buvid4):
        cookies["buvid4"] = buvid4

    nav = _fetch_bilibili_json(
        _BILIBILI_NAV_ENDPOINT,
        {},
        timeout,
        cookies=cookies,
        allow_auth_required_nav=True,
    )
    wbi_img = nav.get("wbi_img")
    if not isinstance(wbi_img, Mapping):
        raise BilibiliLookupError("malformed")
    img_key = _wbi_asset_key(wbi_img.get("img_url"))
    sub_key = _wbi_asset_key(wbi_img.get("sub_url"))
    if img_key is None or sub_key is None:
        raise BilibiliLookupError("malformed")
    return img_key, sub_key, cookies


def _sign_wbi_params(params: Mapping[str, Any], img_key: str, sub_key: str) -> dict[str, str | int]:
    """Sign WBI query fields using Bilibili's published key permutation."""
    mixed = img_key + sub_key
    if len(mixed) < 64 or any(index >= len(mixed) for index in _WBI_MIXIN_KEY_ENC_TAB):
        raise BilibiliLookupError("malformed")
    mixin_key = "".join(mixed[index] for index in _WBI_MIXIN_KEY_ENC_TAB)[:32]
    ordered: dict[str, str | int] = {
        key: "".join(character for character in str(value) if character not in "!'()*")
        for key, value in params.items()
        if key != "w_rid"
    }
    ordered["wts"] = int(time.time())
    ordered = dict(sorted(ordered.items()))
    query = urlencode(ordered)
    ordered["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return ordered


def _detail_matches_id(external_id: str, detail: Mapping[str, Any]) -> bool:
    if _BVID_RE.fullmatch(external_id):
        return str(detail.get("bvid") or "") == external_id
    if _AVID_RE.fullmatch(external_id):
        try:
            return int(detail.get("aid")) == int(external_id[2:])
        except (TypeError, ValueError):
            return False
    return False


def resolve_archive_metadata(
    work: Any,
    *,
    source_context: Mapping[str, Any] | None = None,
    existing_metadata: Mapping[str, Any] | None = None,
    query_bilibili_detail: bool = True,
    timeout: float = 8.0,
) -> ArchiveMetadataResolution:
    """Merge validated collector evidence and an optional Bilibili detail lookup.

    Other platforms use only their already-available collector payload. Bilibili
    requests use a stable external ID and the fixed official view endpoint; no
    work URL, redirect, cookie, or credential is fetched or sent.
    """
    platform = str(_work_value(work, "platform", "") or "")
    external_id = str(_work_value(work, "external_id", "") or "")
    url_value = _work_value(work, "url")
    url = str(url_value) if isinstance(url_value, str) and url_value else None
    if timeout < 0.5 or timeout > 20:
        raise ValueError("metadata timeout must be between 0.5 and 20 seconds")

    title, published, owner_id, owner_name, duration = _existing_seed(work, existing_metadata)
    fields = {
        "title": title,
        "published_at": published,
        "owner_id": owner_id,
        "owner_name": owner_name,
        "duration_seconds": duration,
    }
    issues: list[str] = []
    conflicts, conflict_evidence = _existing_conflicts(existing_metadata)
    check_time = None
    prior_check = (existing_metadata or {}).get("metadata_checked_at")
    if isinstance(prior_check, str) and _datetime_value(prior_check):
        check_time = _datetime_value(prior_check)[0]

    identity_issue = _identity_error(platform, external_id, url)
    if identity_issue:
        issues.append(identity_issue)
        return ArchiveMetadataResolution(
            platform, external_id, **fields,
            metadata_checked_at=check_time,
            check_status="conflict",
            issues=tuple(issues),
        )

    collector_valid = False
    if source_context is not None:
        if _collector_context_matches(platform, external_id, url, source_context):
            collector_valid = True
            for name, incoming in _collector_field_values(platform, source_context).items():
                fields[name] = _merge_preserving(fields[name], incoming, name, conflicts, conflict_evidence)
        else:
            issues.append("collector_identity_mismatch")
            conflicts.append("collector_identity")

    detail_succeeded = False
    if platform == "bilibili" and query_bilibili_detail:
        try:
            detail = _fetch_bilibili_json(
                _BILIBILI_VIEW_ENDPOINT,
                _bilibili_request_id(external_id),
                timeout,
            )
            if not _detail_matches_id(external_id, detail):
                issues.append("bilibili_detail_identity_mismatch")
                if "external_id" not in conflicts:
                    conflicts.append("external_id")
            else:
                _merge_bilibili_detail(fields, detail, conflicts, conflict_evidence)
                detail_succeeded = True
        except BilibiliLookupError as exc:
            issues.append(f"bilibili_{exc.category}")
        except (ValueError, TypeError):
            issues.append("bilibili_identity_invalid")

    if collector_valid or detail_succeeded:
        check_time = _now_utc()
    if conflicts:
        status: ArchiveCheckStatus = "conflict"
    elif detail_succeeded or (collector_valid and any(field.verified for field in fields.values())):
        # A Bilibili detail failure remains visible even if collector fields are
        # retained; it does not erase their field-level evidence.
        status = "needs_review" if issues else "verified"
    elif issues:
        status = "failed" if not any(field.value is not None for field in fields.values()) else "needs_review"
    else:
        status = "needs_review"

    return ArchiveMetadataResolution(
        platform=platform,
        external_id=external_id,
        title=fields["title"],
        published_at=fields["published_at"],
        owner_id=fields["owner_id"],
        owner_name=fields["owner_name"],
        duration_seconds=fields["duration_seconds"],
        metadata_checked_at=check_time,
        check_status=status,
        issues=tuple(dict.fromkeys(issues)),
        conflicts=tuple(dict.fromkeys(conflicts)),
        conflict_evidence=tuple(conflict_evidence),
    )


def _candidate_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = html.unescape(value)
    text = re.sub(r"</?em(?:\s+class=[^>]*)?>", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split()).strip()
    return text or None


def _space_candidate(item: Mapping[str, Any], requested_owner: str) -> BilibiliCandidate | None:
    bvid = item.get("bvid")
    title = _candidate_text(item.get("title"))
    if not isinstance(bvid, str) or not _BVID_RE.fullmatch(bvid) or not title:
        return None
    raw_owner = item.get("mid", item.get("author_mid"))
    owner_id = str(raw_owner) if isinstance(raw_owner, (str, int)) and str(raw_owner).isdigit() else None
    owner_name = item.get("author", item.get("owner"))
    if not isinstance(owner_name, str) or not owner_name.strip():
        owner_name = None
    owner_name = owner_name.strip() if owner_name else None

    duration_value = item.get("duration")
    duration = _duration_seconds(duration_value)
    duration_source = "bilibili_space_wbi_arc_search.duration" if duration is not None else None
    if duration is None:
        duration = _duration_seconds(item.get("length"))
        duration_source = "bilibili_space_wbi_arc_search.length" if duration is not None else None
    publication = _timestamp_seconds(item.get("created"))
    return BilibiliCandidate(
        bvid=bvid,
        title=title,
        owner_id=owner_id,
        owner_id_source="bilibili_space_wbi_arc_search.mid" if owner_id else None,
        owner_name=owner_name,
        owner_name_source="bilibili_space_wbi_arc_search.author" if owner_name else None,
        duration_seconds=duration,
        duration_source=duration_source,
        published_at=publication,
        publication_source="bilibili_space_wbi_arc_search.created" if publication else None,
        publication_precision="second" if publication else None,
        source_timezone="UTC" if publication else None,
        source="bilibili_space_wbi_arc_search",
    )


def discover_bilibili_creator_candidates(
    owner_id: str | int,
    *,
    max_pages: int = 8,
    page_size: int = 30,
    max_retries: int = 2,
    delay_seconds: float = 0.6,
    timeout: float = 8.0,
) -> BilibiliCandidateDiscovery:
    """Fetch a bounded creator-post candidate list; partial lists are never complete.

    The adapter exposes identity/title/owner/duration/publication evidence but
    does not match a directory. Every retry/page count and delay is bounded;
    platform rate control raises ``BilibiliLookupError(category='risk_control')``.
    """
    owner = str(owner_id).strip()
    if not owner.isdigit() or int(owner) <= 0 or len(owner) > 20:
        raise ValueError("owner_id must be a positive Bilibili numeric ID")
    if not 1 <= max_pages <= 10:
        raise ValueError("max_pages must be between 1 and 10")
    if not 1 <= page_size <= 50:
        raise ValueError("page_size must be between 1 and 50")
    if not 0 <= max_retries <= 2:
        raise ValueError("max_retries must be between 0 and 2")
    if not 0 <= delay_seconds <= 3 or not 0.5 <= timeout <= 20:
        raise ValueError("candidate lookup delay or timeout is outside its safe bound")

    img_key, sub_key, cookies = _bilibili_wbi_material(timeout)

    candidates: dict[str, BilibiliCandidate] = {}
    pages_fetched = 0
    reported_pages: int | None = None
    reported_count: int | None = None
    exhausted = False
    malformed = False
    issues: list[str] = []
    for page_number in range(1, max_pages + 1):
        if page_number > 1 and delay_seconds:
            time.sleep(delay_seconds)
        page_data: Mapping[str, Any] | None = None
        last_error: BilibiliLookupError | None = None
        for attempt in range(max_retries + 1):
            try:
                response_data = _fetch_bilibili_json(
                    _BILIBILI_SPACE_WBI_ENDPOINT,
                    _sign_wbi_params(
                        {"mid": int(owner), "pn": page_number, "ps": page_size, "order": "pubdate"},
                        img_key,
                        sub_key,
                    ),
                    timeout,
                    cookies=cookies,
                )
                page_data = response_data
                break
            except BilibiliLookupError as exc:
                last_error = exc
                if exc.category == "risk_control":
                    raise BilibiliLookupError("risk_control", pages_fetched=pages_fetched) from None
                if attempt >= max_retries:
                    raise BilibiliLookupError(exc.category, pages_fetched=pages_fetched) from None
                if delay_seconds:
                    time.sleep(min(delay_seconds * (attempt + 1), 1.5))
        if page_data is None:
            category = last_error.category if last_error else "malformed"
            raise BilibiliLookupError(category, pages_fetched=pages_fetched)

        pages_fetched += 1
        listing = page_data.get("list")
        vlist = listing.get("vlist") if isinstance(listing, Mapping) else None
        if not isinstance(vlist, list):
            raise BilibiliLookupError("malformed", pages_fetched=pages_fetched)
        page_info = page_data.get("page")
        if not isinstance(page_info, Mapping):
            malformed = True
            issues.append("missing_pagination_metadata")
            break
        count, pn, ps = (page_info.get(key) for key in ("count", "pn", "ps"))
        if (
            any(isinstance(value, bool) or not isinstance(value, int) for value in (count, pn, ps))
            or count < 0 or pn != page_number or ps != page_size
        ):
            malformed = True
            issues.append("invalid_pagination_metadata")
            break
        total_pages = (count + ps - 1) // ps
        if "pages" in page_info and (
            isinstance(page_info["pages"], bool)
            or not isinstance(page_info["pages"], int)
            or page_info["pages"] != total_pages
        ):
            malformed = True
            issues.append("inconsistent_reported_page_count")
            break
        if reported_count is not None and reported_count != count:
            malformed = True
            issues.append("inconsistent_reported_candidate_count")
            break
        reported_count, reported_pages = count, total_pages
        if len(vlist) > page_size:
            malformed = True
            issues.append("oversized_candidate_page")

        if not vlist:
            if reported_pages is not None and page_number < reported_pages:
                malformed = True
                issues.append("empty_page_before_reported_end")
                continue
            exhausted = True
            break
        if reported_pages == 0:
            malformed = True
            issues.append("nonempty_page_with_zero_reported_pages")
        for raw_item in vlist:
            if not isinstance(raw_item, Mapping):
                malformed = True
                issues.append("malformed_candidate_row")
                continue
            candidate = _space_candidate(raw_item, owner)
            if candidate is None:
                malformed = True
                issues.append("malformed_candidate_row")
                continue
            # Never treat a different owner row as a candidate for this list.
            if candidate.owner_id is not None and candidate.owner_id != owner:
                raise BilibiliLookupError("malformed", pages_fetched=pages_fetched)
            candidates.setdefault(candidate.bvid, candidate)

        if reported_pages is not None and page_number >= reported_pages:
            exhausted = True
            break
        if reported_pages is not None and len(vlist) < page_size:
            malformed = True
            issues.append("short_page_before_reported_end")
    if exhausted and reported_count != len(candidates):
        malformed = True
        issues.append("candidate_count_mismatch")
    complete = exhausted and not malformed
    truncated = not exhausted
    return BilibiliCandidateDiscovery(
        owner_id=owner,
        candidates=tuple(candidates.values()),
        pages_fetched=pages_fetched,
        max_pages=max_pages,
        complete=complete,
        truncated=truncated,
        issues=tuple(dict.fromkeys(issues)),
    )


def verify_bilibili_candidate(
    candidate: BilibiliCandidate,
    *,
    expected_owner_id: str | int,
    expected_title: str,
    expected_duration_seconds: int | None = None,
    timeout: float = 8.0,
) -> BilibiliCandidateVerification:
    """Verify exact ID, owner, title, and optional duration against the detail API.

    No fuzzy title matching or numeric/sequence guesses are performed. The
    caller must separately establish that the discovery list was complete and
    that the candidate is unique before associating it with historical media.
    """
    if not _BVID_RE.fullmatch(candidate.bvid):
        raise ValueError("candidate must contain a valid Bilibili BV ID")
    if timeout < 0.5 or timeout > 20:
        raise ValueError("metadata timeout must be between 0.5 and 20 seconds")
    if not isinstance(expected_title, str) or not expected_title.strip():
        raise ValueError("expected_title must be a nonempty string")
    expected_owner = str(expected_owner_id).strip()
    issues: list[str] = []
    if not expected_owner.isdigit() or int(expected_owner) <= 0:
        raise ValueError("expected_owner_id must be a positive numeric ID")
    if (
        isinstance(expected_duration_seconds, bool)
        or not isinstance(expected_duration_seconds, int)
        or expected_duration_seconds <= 0
    ):
        issues.append("expected_duration_missing")
    if candidate.owner_id is not None and candidate.owner_id != expected_owner:
        issues.append("candidate_owner_mismatch")
    try:
        detail = _fetch_bilibili_json(
            _BILIBILI_VIEW_ENDPOINT,
            {"bvid": candidate.bvid},
            timeout,
        )
    except BilibiliLookupError as exc:
        return BilibiliCandidateVerification(
            bvid=candidate.bvid,
            verified=False,
            detail_title=None,
            owner_id=None,
            owner_name=None,
            duration_seconds=None,
            published_at=None,
            publication_source=None,
            publication_precision=None,
            source_timezone=None,
            metadata_checked_at=None,
            issues=(f"detail_{exc.category}",),
        )

    checked_at = _now_utc()
    owner = detail.get("owner") if isinstance(detail.get("owner"), Mapping) else {}
    detail_owner = str(owner.get("mid")) if owner.get("mid") is not None else None
    detail_owner_name = owner.get("name") if isinstance(owner.get("name"), str) else None
    detail_title = detail.get("title") if isinstance(detail.get("title"), str) else None
    detail_duration = _duration_seconds(detail.get("duration"))
    published = _timestamp_seconds(detail.get("pubdate"))
    if not _detail_matches_id(candidate.bvid, detail):
        issues.append("detail_identity_mismatch")
    if detail_owner != expected_owner:
        issues.append("detail_owner_mismatch")
    if candidate.owner_id is not None and detail_owner != candidate.owner_id:
        issues.append("candidate_detail_owner_conflict")
    if detail_title is None or detail_title.strip() != expected_title.strip():
        issues.append("detail_title_mismatch")
    if candidate.title.strip() != expected_title.strip():
        issues.append("candidate_title_mismatch")
    if (
        isinstance(expected_duration_seconds, int)
        and not isinstance(expected_duration_seconds, bool)
        and expected_duration_seconds > 0
    ):
        if detail_duration != expected_duration_seconds:
            issues.append("detail_duration_mismatch")
        if candidate.duration_seconds is not None and candidate.duration_seconds != expected_duration_seconds:
            issues.append("candidate_duration_mismatch")

    return BilibiliCandidateVerification(
        bvid=candidate.bvid,
        verified=not issues,
        detail_title=detail_title,
        owner_id=detail_owner,
        owner_name=detail_owner_name,
        duration_seconds=detail_duration,
        published_at=published,
        publication_source="bilibili_view_api" if published else None,
        publication_precision="second" if published else None,
        source_timezone="UTC" if published else None,
        metadata_checked_at=checked_at,
        issues=tuple(dict.fromkeys(issues)),
    )
