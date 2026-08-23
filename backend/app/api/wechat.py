"""wechat 路由：/api/v1/wechat/import（预留占位，P1 返回 501）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.core.errors import not_implemented
from app.schemas.wechat import WechatImportRequest

router = APIRouter(prefix="/api/v1/wechat", tags=["wechat"], dependencies=[Depends(require_admin)])


@router.post("/import", status_code=501)
def wechat_import(_payload: WechatImportRequest):
    raise not_implemented("NOT_IMPLEMENTED")
