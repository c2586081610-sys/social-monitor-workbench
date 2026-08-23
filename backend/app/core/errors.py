"""业务异常 + 统一错误码（对齐 SPEC §4.1 与 openapi-aggregator.yaml）。

错误码约定：
0    成功
401  未认证（AUTH_REQUIRED）
404  资源不存在（NOT_FOUND）
409  冲突（CONFLICT / 非法状态迁移）
422  参数校验失败（VALIDATION_ERROR）
501  功能未实现（NOT_IMPLEMENTED）
1001 流水线引擎离线（PIPELINE_OFFLINE, HTTP 503）
1002 监控层离线（MONITOR_OFFLINE, HTTP 503）
2001 Cookie 失效需重登（COOKIE_NEEDS_RELOGIN, HTTP 409）
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """业务异常：携带 code / message / http_status / data。"""

    def __init__(
        self,
        code: int,
        message: str,
        http_status: int | None = None,
        data: Any = None,
    ) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status if http_status is not None else code
        self.data = data
        super().__init__(message)


def ok(data: Any, message: str = "") -> dict:
    """统一成功响应包装 {code:0, data, message}。"""
    return {"code": 0, "data": data, "message": message}


def unauthorized(message: str = "AUTH_REQUIRED") -> AppError:
    return AppError(401, message, http_status=401)


def not_found(message: str = "NOT_FOUND") -> AppError:
    return AppError(404, message, http_status=404)


def conflict(message: str = "CONFLICT") -> AppError:
    return AppError(409, message, http_status=409)


def validation(message: str = "VALIDATION_ERROR") -> AppError:
    return AppError(422, message, http_status=422)


def not_implemented(message: str = "NOT_IMPLEMENTED") -> AppError:
    return AppError(501, message, http_status=501)


def pipeline_offline(message: str = "PIPELINE_OFFLINE") -> AppError:
    return AppError(1001, message, http_status=503)


def monitor_offline(message: str = "MONITOR_OFFLINE") -> AppError:
    return AppError(1002, message, http_status=503)


def cookie_needs_relogin(message: str = "COOKIE_NEEDS_RELOGIN") -> AppError:
    return AppError(2001, message, http_status=409)
