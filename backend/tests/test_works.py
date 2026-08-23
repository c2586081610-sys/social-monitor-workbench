"""works 列表/详情/重试/分析/归类/关键帧 冒烟测试。"""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.repositories import tag_repo, task_repo, work_repo


def _make_work(db, *, external_id="av-1", status="NEW", creator_id=None, group_id=None, source_type="monitor"):
    work = work_repo.upsert(
        db,
        "bilibili",
        external_id,
        title=f"作品{external_id}",
        url=f"https://bilibili.com/video/{external_id}",
        published_at="2026-08-22T08:00:00Z",
        creator_id=creator_id,
        group_id=group_id,
        source_type=source_type,
        status=status,
    )
    db.commit()
    return work


def test_list_works_filter_and_pagination(client, auth_headers, db):
    _make_work(db, external_id="av-list-1", status="DONE")
    _make_work(db, external_id="av-list-2", status="QUEUED")
    resp = client.get("/api/v1/works?status=QUEUED&limit=10", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["total"] >= 1
    assert all(item["status"] == "QUEUED" for item in body["items"])

    resp = client.get("/api/v1/works?q=作品av-list-1", headers=auth_headers)
    assert resp.status_code == 200
    assert any(item["external_id"] == "av-list-1" for item in resp.json()["data"]["items"])


def test_work_detail_with_stages_and_tags(client, auth_headers, db):
    work = _make_work(db, external_id="av-detail-1", status="DONE")
    tag = tag_repo.create(db, "利率-详情", kind="small")
    tag_repo.link_work(db, work.id, tag.id)
    task_repo.upsert(db, work.id, "download", "succeeded", attempts=1)
    db.commit()

    resp = client.get(f"/api/v1/works/{work.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(t["name"] == "利率-详情" for t in data["tags"])
    assert any(s["stage"] == "download" and s["status"] == "succeeded" for s in data["stages"])
    assert data["source_type"] == "monitor"


def test_work_retry_failed_to_queued(client, auth_headers, db):
    work = _make_work(db, external_id="av-retry-1", status="FAILED")
    resp = client.post(f"/api/v1/works/{work.id}/retry", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "QUEUED"
    assert data["retry_count"] >= 1

    # 非 FAILED 不可重试 → 409
    resp = client.post(f"/api/v1/works/{work.id}/retry", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == 409


def test_work_analyze_writes_pending_manifest(client, auth_headers, db):
    work = _make_work(db, external_id="av-analyze-1", status="DONE")
    resp = client.post(f"/api/v1/works/{work.id}/analyze", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["note_pending"] is True
    assert data["pending_file"].startswith("workbuddy/pending/")

    manifest_path = settings.pending_dir / Path(data["pending_file"]).name
    assert manifest_path.exists()

    # 状态进入 NOTE_GENERATING
    resp = client.get(f"/api/v1/works/{work.id}", headers=auth_headers)
    assert resp.json()["data"]["status"] == "NOTE_GENERATING"


def test_work_classify_sets_group_tags_done(client, auth_headers, db):
    group = client.post("/api/v1/groups", json={"name": "财经"}, headers=auth_headers).json()["data"]
    work = _make_work(db, external_id="av-classify-1", status="UNCLASSIFIED")

    resp = client.post(
        f"/api/v1/works/{work.id}/classify",
        json={"group_id": group["id"], "tags": ["美联储", "A股"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "DONE"
    assert data["group_id"] == group["id"]

    resp = client.get(f"/api/v1/works/{work.id}", headers=auth_headers)
    assert {t["name"] for t in resp.json()["data"]["tags"]} == {"美联储", "A股"}


def test_work_frames_missing_manifest_returns_empty(client, auth_headers, db):
    work = _make_work(db, external_id="av-frames-1", status="DONE")
    resp = client.get(f"/api/v1/works/{work.id}/frames", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


def test_work_frames_reads_manifest(client, auth_headers, db, tmp_path):
    work = _make_work(db, external_id="av-frames-2", status="DONE")
    manifest_rel = "财经/博主/2026-08-22-x/frames/frame_manifest.json"
    manifest_path = settings.media_root / manifest_rel
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        '{"work_id": %d, "semantic_aligned": true, "fallback": false, "frames": [{"file": "frames/frame_0001.jpg", "time_seconds": 42.5, "hits": [{"term": "A股", "action": "increase", "weight": 1.0}], "confidence": 0.9}]}'
        % work.id,
        encoding="utf-8",
    )
    work_repo.update(db, work, frame_manifest_path=manifest_rel)
    db.commit()

    resp = client.get(f"/api/v1/works/{work.id}/frames", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["semantic_aligned"] is True
    assert len(data["items"]) == 1
    assert data["items"][0]["hits"][0]["term"] == "A股"

    # 列表/详情接口 frame_count 读 manifest
    resp = client.get(f"/api/v1/works/{work.id}", headers=auth_headers)
    assert resp.json()["data"]["frame_count"] == 1
