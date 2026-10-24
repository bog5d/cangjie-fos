"""对外 API 错误体：短码 + 摘要；细节仅进日志。"""
from __future__ import annotations

import logging
import os
import traceback
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

E_INTERNAL = "E_INTERNAL"
E_QUEUE_FULL = "E_QUEUE_FULL"


def _expose_detail() -> bool:
    return (os.getenv("CANGJIE_EXPOSE_ERROR_DETAIL") or "").strip().lower() in {"1", "true", "yes"}


def public_http_exception_payload(status: int, code: str, message: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "request_id": request_id},
    }


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", "") or ""
    if _expose_detail():
        msg = f"{type(exc).__name__}: {exc}"
    else:
        msg = "服务器内部错误，请稍后重试或联系管理员"
    logger.exception("unhandled request_id=%s path=%s", rid, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=public_http_exception_payload(500, E_INTERNAL, msg, rid),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    rid = getattr(request.state, "request_id", "") or ""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        msg = str(detail.get("message", detail))
        body = {
            "detail": msg,
            "error": {**detail, "request_id": rid},
        }
        return JSONResponse(status_code=exc.status_code, content=body)
    msg = str(detail) if detail else exc.__class__.__name__
    code = "E_HTTP"
    if exc.status_code == 429:
        code = E_QUEUE_FULL
    elif exc.status_code == 413:
        code = "E_PAYLOAD_TOO_LARGE"
    err = public_http_exception_payload(exc.status_code, code, msg, rid)
    # 保留 FastAPI/Starlette 惯用的 `detail` 字符串，避免破坏既有客户端与单测
    err["detail"] = msg
    return JSONResponse(status_code=exc.status_code, content=err)
