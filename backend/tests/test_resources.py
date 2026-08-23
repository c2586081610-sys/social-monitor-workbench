"""groups / tags / lexicon / unclassified / health / monitor / wechat 冒烟测试。"""
from __future__ import annotations

from app.repositories import work_repo


def test_group_crud_and_delete_moves_creators(client, auth_headers):
    created = client.post("/api/v1/groups", json={"name": "科技"}, headers=auth_headers).json()["data"]
    assert created["name"] == "科技"

    creator = client.post(
        "/api/v1/creators",
        json={
            "platform": "twitter",
            "name": "推特博主",
            "profile_url": "https://twitter.com/handle1",
            "external_id": "handle1",
            "group_id": created["id"],
        },
        headers=auth_headers,
    ).json()["data"]

    groups = client.get("/api/v1/groups", headers=auth_headers).json()["data"]["items"]
    group = next(g for g in groups if g["id"] == created["id"])
    assert group["creator_count"] >= 1

    # 重命名
    renamed = client.patch(f"/api/v1/groups/{created['id']}", json={"name": "科技2"}, headers=auth_headers).json()["data"]
    assert renamed["name"] == "科技2"

    # 删除 → 博主移入未分组
    resp = client.delete(f"/api/v1/groups/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["moved_creators"] >= 1

    detail = client.get(f"/api/v1/creators/{creator['id']}", headers=auth_headers).json()["data"]
    assert detail["group_id"] is None


def test_group_duplicate_conflict(client, auth_headers):
    client.post("/api/v1/groups", json={"name": "重复组"}, headers=auth_headers)
    resp = client.post("/api/v1/groups", json={"name": "重复组"}, headers=auth_headers)
    assert resp.status_code == 409


def test_tags_list_and_works_by_tag(client, auth_headers, db):
    tag = client.post("/api/v1/lexicon", json={"term": "占位", "action": "increase"}, headers=auth_headers)
    assert tag.status_code == 201

    # 直接给作品打标签（模拟 AI 生成双层标签后落库）
    from app.repositories import tag_repo
    from app.services.group_service import group_service

    group = group_service.create(db, "标签组")
    work = work_repo.upsert(
        db, "xhs", "note-tag-1",
        title="标签测试作品", url="https://xhs.com/note/note-tag-1",
        published_at="2026-08-22T08:00:00Z", source_type="monitor", status="UNCLASSIFIED",
    )
    db.commit()
    tag_entity = tag_repo.create(db, "美联储", kind="small")
    tag_repo.link_work(db, work.id, tag_entity.id)
    db.commit()

    resp = client.get("/api/v1/tags?kind=small", headers=auth_headers)
    assert resp.status_code == 200
    tag_item = next(t for t in resp.json()["data"]["items"] if t["name"] == "美联储")
    assert tag_item["work_count"] >= 1

    resp = client.get("/api/v1/tags/美联储/works", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] >= 1


def test_lexicon_crud(client, auth_headers):
    created = client.post(
        "/api/v1/lexicon",
        json={"term": "A股", "action": "increase", "weight": 1.5},
        headers=auth_headers,
    ).json()["data"]
    assert created["weight"] == 1.5

    updated = client.patch(
        f"/api/v1/lexicon/{created['id']}",
        json={"action": "decrease", "enabled": False},
        headers=auth_headers,
    ).json()["data"]
    assert updated["action"] == "decrease"
    assert updated["enabled"] is False

    resp = client.delete(f"/api/v1/lexicon/{created['id']}", headers=auth_headers)
    assert resp.json()["data"] == {"deleted": True}

    # 重复词条 → 409
    client.post("/api/v1/lexicon", json={"term": "A股", "action": "increase"}, headers=auth_headers)
    resp = client.post("/api/v1/lexicon", json={"term": "A股", "action": "increase"}, headers=auth_headers)
    assert resp.status_code == 409


def test_unclassified_queue(client, auth_headers, db):
    work_repo.upsert(
        db, "douyin", "aweme-unc-1",
        title="待分类作品", url="https://douyin.com/video/aweme-unc-1",
        published_at="2026-08-22T08:00:00Z", source_type="like", status="UNCLASSIFIED",
    )
    db.commit()
    resp = client.get("/api/v1/unclassified", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] >= 1


def test_health_cookie_and_system(client, auth_headers):
    resp = client.get("/api/v1/health/cookie", headers=auth_headers)
    assert resp.status_code == 200
    platforms = {item["platform"] for item in resp.json()["data"]["items"]}
    assert {"douyin", "bilibili", "xhs", "twitter"} <= platforms

    resp = client.get("/api/v1/health/system", headers=auth_headers)
    assert resp.status_code == 200
    components = {item["component"]: item["status"] for item in resp.json()["data"]["items"]}
    assert components["aggregator"] == "online"
    assert components["monitor"] == "offline"  # 测试环境无心跳
    assert components["workbuddy_pending"] == "online"


def test_monitor_poll_offline_when_no_heartbeat(client, auth_headers):
    # 测试环境未启动监控层 → 1002 MONITOR_OFFLINE
    resp = client.post("/api/v1/monitor/poll", json={}, headers=auth_headers)
    assert resp.status_code == 503
    assert resp.json()["code"] == 1002


def test_wechat_import_not_implemented(client, auth_headers):
    resp = client.post(
        "/api/v1/wechat/import",
        json={"url": "https://mp.weixin.qq.com/s/xxx"},
        headers=auth_headers,
    )
    assert resp.status_code == 501
    assert resp.json()["code"] == 501
