"""依赖注入：db session + Bearer token 校验。"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.security import verify_admin_token

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    token = credentials.credentials if credentials else None
    if not verify_admin_token(token):
        from app.core.errors import unauthorized

        raise unauthorized()
