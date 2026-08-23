"""与聚合 API 共享 SQLite：只经 repository 层读写，不重复定义模型。"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal, init_db  # noqa: E402

__all__ = ["settings", "SessionLocal", "init_db"]
