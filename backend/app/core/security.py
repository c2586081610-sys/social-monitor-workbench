"""安全：Bearer token 校验 + Fernet 加密工具（cookie 加密存储，不落明文日志）。

凭据本体不落数据库（SPEC §5 cookies 表注）；token 校验用常量时间比较。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import unauthorized


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_admin_token(token: str | None) -> bool:
    """常量时间比较，防止时序侧信道。"""
    if not token:
        return False
    expected = _digest(settings.admin_token)
    actual = _digest(token)
    return hmac.compare_digest(expected, actual)


def require_admin_token(token: str | None) -> None:
    if not verify_admin_token(token):
        raise unauthorized()


def _fernet() -> Fernet:
    key = settings.fernet_key
    if not key:
        # 未配置密钥时生成本地文件密钥（仅开发兜底；生产必须配置 FERNET_KEY）
        key = _load_or_create_dev_key()
    return Fernet(key)


def _load_or_create_dev_key() -> str:
    key_file = settings.workbuddy_dir / ".fernet_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = Fernet.generate_key().decode("utf-8")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key, encoding="utf-8")
    return key


def encrypt_secret(plain: str) -> str:
    """加密敏感凭据（cookie 原文等）。禁止把明文写日志。"""
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("解密失败：FERNET_KEY 不匹配或数据损坏") from exc


def random_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
