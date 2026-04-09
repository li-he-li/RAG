"""
Reject oversized non-multipart request bodies using Content-Length (JSON / NDJSON APIs).
"""

from __future__ import annotations

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class MaxJsonBodyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path or ""
        if not path.startswith("/api"):
            return await call_next(request)
        ct = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" in ct:
            return await call_next(request)
        raw = request.headers.get("content-length")
        if not raw or not raw.isdigit():
            return await call_next(request)
        n = int(raw)
        if n > self._max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "请求体过大（请缩小 JSON 或减少单次提交内容）。"},
            )
        return await call_next(request)
