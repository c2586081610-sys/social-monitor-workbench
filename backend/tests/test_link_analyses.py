"""手动链接分析入口：先验证入库契约，再接入本地流水线。"""
from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.services.link_analysis_service import parse_link_identity


def _payload(**overrides):
    data = {
        "url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "platform": "bilibili",
        "external_id": "BV1xx411c7mD",
        "mode": "one_time",
    }
    data.update(overrides)
    return data


def test_create_manual_link_work_is_idempotent_and_visible(client, auth_headers):
    first = client.post("/api/v1/link-analyses", json=_payload(), headers=auth_headers)
    second = client.post("/api/v1/link-analyses", json=_payload(), headers=auth_headers)

    assert first.status_code == 201
    first_data = first.json()["data"]
    assert first_data["created"] is True
    assert first_data["mode"] == "one_time"
    assert first_data["work"]["source_type"] == "manual"
    assert first_data["work"]["status"] == "QUEUED"

    assert second.status_code == 201
    second_data = second.json()["data"]
    assert second_data["created"] is False
    assert second_data["work"]["id"] == first_data["work"]["id"]

    detail = client.get(f"/api/v1/works/{first_data['work']['id']}", headers=auth_headers)
    assert detail.status_code == 200
    stages = {stage["stage"]: stage["status"] for stage in detail.json()["data"]["stages"]}
    assert stages == {
        "parse": "pending",
        "download": "pending",
        "transcribe": "pending",
        "frames": "pending",
        "note": "pending",
    }


def test_rejects_url_that_does_not_match_supplied_platform(client, auth_headers):
    response = client.post(
        "/api/v1/link-analyses",
        json=_payload(platform="xhs", external_id="673adb17000000001d037a1f"),
        headers=auth_headers,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("url", "platform", "external_id"),
    [
        ("https://www.douyin.com/video/7412345678901234567", "douyin", "7412345678901234567"),
        ("https://www.xiaohongshu.com/explore/673adb17000000001d037a1f", "xhs", "673adb17000000001d037a1f"),
        ("https://x.com/example/status/1234567890123456789", "twitter", "1234567890123456789"),
    ],
)
def test_parse_link_identity_recognizes_remaining_supported_video_hosts(url, platform, external_id):
    identity = parse_link_identity(url)

    assert identity.platform == platform
    assert identity.external_id == external_id


def test_parse_known_short_link_after_redirect_resolution():
    identity = parse_link_identity(
        "https://b23.tv/short-code",
        resolve_redirect=lambda _url: "https://www.bilibili.com/video/BV1xx411c7mD",
    )

    assert identity.platform == "bilibili"
    assert identity.external_id == "BV1xx411c7mD"


def test_short_link_redirect_to_unsupported_host_is_rejected():
    with pytest.raises(AppError, match="LINK_IDENTITY_UNSUPPORTED"):
        parse_link_identity(
            "https://b23.tv/short-code",
            resolve_redirect=lambda _url: "https://example.com/video/anything",
        )
