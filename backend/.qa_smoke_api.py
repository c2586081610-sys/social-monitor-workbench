# -*- coding: utf-8 -*-
"""QA 冒烟: 后端 API 启动 + 核心端点可达（带 token）"""
import sys, os
sys.path.insert(0, ".")
os.environ["DATABASE_PATH"] = r"C:/Users/Administrator/WorkBuddy/2026-08-22-18-25-30/aggregator.db"
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
H = {"Authorization": "Bearer dev-admin-token-change-me"}
for path in ["/api/v1/health/system", "/api/v1/health/cookie", "/api/v1/creators", "/api/v1/groups", "/api/v1/tags", "/api/v1/works", "/api/v1/unclassified"]:
    r = c.get(path, headers=H)
    print(f"GET {path} -> {r.status_code}")
r = c.get("/api/v1/lexicon/entries", headers=H)
print(f"GET /api/v1/lexicon/entries -> {r.status_code}")
print("== POST /monitor/poll ==")
r = c.post("/api/v1/monitor/poll", json={"platform": "douyin"}, headers=H)
print("POST /api/v1/monitor/poll ->", r.status_code, r.text[:150])
