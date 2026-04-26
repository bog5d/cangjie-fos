"""Request-ID、可选体大小、简易全局限流、可选 API Key。"""
from __future__ import annotations

import os
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from cangjie_fos.core.http_errors import public_http_exception_payload
from cangjie_fos.core.limits import max_json_body_bytes

_RATE_WINDOW_SEC = 60.0
_rate_hits: dict[str, list[float]] = {}


def _max_rpm() -> int:
    raw = (os.getenv("CANGJIE_MAX_REQUESTS_PER_MINUTE") or "300").strip()
    try:
        return max(30, min(10000, int(raw)))
    except ValueError:
        return 300


def _check_rate(client_ip: str) -> bool:
    now = time.time()
    bucket = _rate_hits.setdefault(client_ip, [])
    while bucket and now - bucket[0] > _RATE_WINDOW_SEC:
        bucket.pop(0)
    cap = _max_rpm()
    if len(bucket) >= cap:
        return False
    bucket.append(now)
    return True


class RequestContextMiddleware(BaseHTTPMiddleware):
    """注入 request.state.request_id，并在响应头回显 X-Request-ID；可选限制 Content-Length。"""

    def __init__(self, app, *, check_body_size: bool = True) -> None:
        super().__init__(app)
        self._check = check_body_size

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = (request.headers.get("x-request-id") or "").strip() or uuid.uuid4().hex
        request.state.request_id = rid
        p = request.url.path

        client = request.client.host if request.client else "unknown"
        if p.startswith("/api") and not _check_rate(client):
            return JSONResponse(
                status_code=429,
                content=public_http_exception_payload(
                    429, "E_RATE_LIMIT", "请求过于频繁，请稍后再试", rid
                ),
                headers={"X-Request-ID": rid, "Retry-After": "60"},
            )

        if self._check and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            cl = request.headers.get("content-length")
            if cl:
                try:
                    n = int(cl)
                    max_b = max_json_body_bytes()
                    if n > max_b:
                        return JSONResponse(
                            status_code=413,
                            content=public_http_exception_payload(
                                413,
                                "E_JSON_BODY_TOO_LARGE",
                                f"请求体超过限制（{max_b // (1024 * 1024)}MB）",
                                rid,
                            ),
                            headers={"X-Request-ID": rid},
                        )
                except ValueError:
                    pass

        key = os.getenv("CANGJIE_API_KEY", "").strip()
        if key and p.startswith("/api"):
            public_api = p in ("/api/v1/ready",) or p.endswith("/health") or p == "/api/pitch/health"
            if not public_api:
                auth = (request.headers.get("authorization") or "").strip()
                xk = (request.headers.get("x-api-key") or "").strip()
                token = ""
                if auth.lower().startswith("bearer "):
                    token = auth[7:].strip()
                elif xk:
                    token = xk
                if not token or token != key:
                    return JSONResponse(
                        status_code=401,
                        content=public_http_exception_payload(
                            401, "E_UNAUTHORIZED", "需要有效 API 密钥", rid
                        ),
                        headers={"X-Request-ID": rid},
                    )

        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
