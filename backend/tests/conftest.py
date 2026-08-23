"""pytest 夹具：隔离临时目录 + TestClient。env 必须在 import app 前设置（settings 为单例）。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="aggregator-test-"))
os.environ["ADMIN_TOKEN"] = "test-token"
os.environ["DATABASE_PATH"] = str(_TMP / "aggregator.db")
os.environ["MEDIA_ROOT"] = str(_TMP / "media")
os.environ["OBSIDIAN_ROOT"] = str(_TMP / "Obsidian")
os.environ["WORKBUDDY_DIR"] = str(_TMP / "workbuddy")
os.environ["MONITOR_HEARTBEAT_TIMEOUT"] = "60"
os.environ["RSSHUB_BASE_URL"] = ""
os.environ["CHANGEDETECTION_URL"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers() -> dict:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture()
def db():
    """独立数据库会话（自动回滚隔离，测试内手动 commit 以走事务路径）。"""
    from app.core.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
