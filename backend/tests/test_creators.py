"""creators CRUD + 鉴权/冲突/校验冒烟测试。"""
from __future__ import annotations

from app.repositories import creator_repo, work_repo


def _creator_payload(**overrides):
    payload = {
        "platform": "bilibili",
        "name": "测试博主",
        "profile_url": "https://space.bilibili.com/12345",
        "external_id": "12345",
    }
    payload.update(overrides)
    return payload


def test_create_and_get_creator(client, auth_headers):
    resp = client.post("/api/v1/creators", json=_creator_payload(), headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["platform"] == "bilibili"
    assert data["enabled"] is True
    creator_id = data["id"]

    resp = client.get(f"/api/v1/creators/{creator_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "测试博主"


def test_list_creators_pagination_and_filter(client, auth_headers):
    client.post("/api/v1/creators", json=_creator_payload(external_id="xhs-1", platform="xhs", name="小红"), headers=auth_headers)
    resp = client.get("/api/v1/creators?platform=xhs&page=1&limit=5", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["total"] >= 1
    assert body["page"] == 1
    assert all(item["platform"] == "xhs" for item in body["items"])

    resp = client.get("/api/v1/creators?q=小红", headers=auth_headers)
    assert resp.status_code == 200
    assert any(item["name"] == "小红" for item in resp.json()["data"]["items"])


def test_update_creator_patch(client, auth_headers):
    created = client.post("/api/v1/creators", json=_creator_payload(external_id="patch-1"), headers=auth_headers).json()["data"]
    resp = client.patch(
        f"/api/v1/creators/{created['id']}",
        json={"name": "改名后", "enabled": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "改名后"
    assert data["enabled"] is False


def test_delete_creator(client, auth_headers):
    created = client.post("/api/v1/creators", json=_creator_payload(external_id="del-1"), headers=auth_headers).json()["data"]
    resp = client.delete(f"/api/v1/creators/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"] == {"deleted": True}
    resp = client.get(f"/api/v1/creators/{created['id']}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == 404


def test_creator_duplicate_conflict(client, auth_headers):
    client.post("/api/v1/creators", json=_creator_payload(external_id="dup-1"), headers=auth_headers)
    resp = client.post("/api/v1/creators", json=_creator_payload(external_id="dup-1"), headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == 409


def test_creator_invalid_platform_422(client, auth_headers):
    resp = client.post(
        "/api/v1/creators",
        json=_creator_payload(platform="not-a-platform"),
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


def test_auth_required(client):
    resp = client.get("/api/v1/creators")
    assert resp.status_code == 401
    assert resp.json()["code"] == 401
    assert resp.json()["message"] == "AUTH_REQUIRED"


def test_creator_works_endpoint(client, auth_headers, db):
    created = client.post("/api/v1/creators", json=_creator_payload(external_id="cw-1"), headers=auth_headers).json()["data"]
    work_repo.upsert(
        db,
        "bilibili",
        "av-cw-1",
        title="作品A",
        url="https://bilibili.com/video/av-cw-1",
        creator_id=created["id"],
        source_type="monitor",
    )
    db.commit()
    resp = client.get(f"/api/v1/creators/{created['id']}/works", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] >= 1
