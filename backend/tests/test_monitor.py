"""monitor 增量测试：/poll-now（立即爬取）与 /poll-status（轮询状态）。"""
from __future__ import annotations

from app.models import PollLog
from app.utils.timeutil import now_iso


class _FakePopen:
    """模拟 subprocess.Popen：记录 cmd，固定 pid。"""

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 4242


def test_monitor_poll_status_empty(client, auth_headers):
    resp = client.get("/api/v1/monitor/poll-status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    items = {item["platform"]: item for item in body["data"]["items"]}
    assert set(items) == {"douyin", "bilibili", "xhs", "twitter"}
    for item in items.values():
        assert item["last_poll_at"] is None
        assert item["status"] == "never"
        assert item["new_works"] == 0
        assert item["detail"] is None


def test_monitor_poll_status_latest_per_platform(client, auth_headers, db):
    db.add(
        PollLog(
            platform="bilibili", status="ok", started_at=now_iso(),
            finished_at="2026-08-27T01:00:00Z", new_works=2,
        )
    )
    db.add(
        PollLog(
            platform="bilibili", status="failed", detail="route 失效 HTTP 502",
            started_at=now_iso(), finished_at="2026-08-27T02:00:00Z", new_works=0,
        )
    )
    db.add(
        PollLog(
            platform="twitter", status="ok", started_at=now_iso(),
            finished_at="2026-08-27T03:00:00Z", new_works=5, detail=None,
        )
    )
    db.commit()

    resp = client.get("/api/v1/monitor/poll-status", headers=auth_headers)
    assert resp.status_code == 200
    items = {item["platform"]: item for item in resp.json()["data"]["items"]}
    assert items["bilibili"]["last_poll_at"] == "2026-08-27T02:00:00Z"
    assert items["bilibili"]["status"] == "failed"
    assert items["bilibili"]["new_works"] == 0
    assert items["bilibili"]["detail"] == "route 失效 HTTP 502"
    assert items["twitter"]["last_poll_at"] == "2026-08-27T03:00:00Z"
    assert items["twitter"]["status"] == "ok"
    assert items["twitter"]["new_works"] == 5
    assert items["twitter"]["detail"] is None
    assert items["douyin"]["last_poll_at"] is None
    assert items["douyin"]["new_works"] == 0


def test_poll_logs_new_works_migration_and_default(client, auth_headers, db):
    """验证 v0.6 迁移：poll_logs 存在 new_works 列且模型默认 0。"""
    from sqlalchemy import text

    cols = {row[1] for row in db.execute(text("PRAGMA table_info(poll_logs)"))}
    assert "new_works" in cols

    log = PollLog(platform="xhs", status="ok", started_at=now_iso(), finished_at=now_iso())
    db.add(log)
    db.commit()
    assert log.new_works == 0

    resp = client.get("/api/v1/monitor/poll-status", headers=auth_headers)
    items = {item["platform"]: item for item in resp.json()["data"]["items"]}
    assert items["xhs"]["new_works"] == 0


def test_monitor_poll_now_validation(client, auth_headers):
    # 未知平台 → 422
    resp = client.post("/api/v1/monitor/poll-now", json={"platform": "wechat"}, headers=auth_headers)
    assert resp.status_code == 422

    # platform 与 creator_id 同时给 → 422
    resp = client.post(
        "/api/v1/monitor/poll-now", json={"platform": "bilibili", "creator_id": 1}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_monitor_poll_now_spawns(client, auth_headers, monkeypatch):
    calls = {}

    def fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return _FakePopen(cmd, **kwargs)

    monkeypatch.setattr("app.services.monitor_service.subprocess.Popen", fake_popen)

    resp = client.post("/api/v1/monitor/poll-now", json={"platform": "bilibili"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["triggered"] is True
    assert data["pid"] == 4242
    assert calls["cmd"][-2:] == ["--platform", "bilibili"]
    assert calls["cmd"][1].endswith("onetime_poll.py")
    assert calls["kwargs"].get("creationflags") is not None

    # creator 透传
    resp = client.post("/api/v1/monitor/poll-now", json={"creator_id": 7}, headers=auth_headers)
    assert resp.status_code == 200
    assert calls["cmd"][-2:] == ["--creator", "7"]

    # 空 body = 全部平台
    resp = client.post("/api/v1/monitor/poll-now", json={}, headers=auth_headers)
    assert resp.status_code == 200
    assert len(calls["cmd"]) == 2  # 仅 python + script
