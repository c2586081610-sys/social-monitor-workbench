"""入口：只装配（app 实例 + 中间件 + include_router + 启动），零业务逻辑。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import creators, groups, health, lexicon, monitor, tags, unclassified, wechat, works
from app.core.config import settings
from app.core.db import init_db
from app.core.errors import AppError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("aggregator")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：启动时建表 + 幂等迁移（替代 FastAPI on_event，消除弃用警告）。"""
    init_db()
    yield


app = FastAPI(
    title="博主监控 + AI 笔记工作台 — 聚合 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "data": exc.data, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"code": 422, "data": None, "message": "VALIDATION_ERROR"})


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "data": None, "message": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"code": 500, "data": None, "message": "INTERNAL_ERROR"})


@app.get("/api/v1/healthz", tags=["health"])
def healthz():
    """无认证存活探针（供部署/运维，不进 openapi 契约）。"""
    return {"code": 0, "data": {"status": "ok"}, "message": ""}


app.include_router(creators.router)
app.include_router(works.router)
app.include_router(groups.router)
app.include_router(tags.router)
app.include_router(unclassified.router)
app.include_router(lexicon.router)
app.include_router(health.router)
app.include_router(monitor.router)
app.include_router(wechat.router)
