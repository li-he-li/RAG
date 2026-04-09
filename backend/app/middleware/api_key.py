"""
Optional shared-secret gate for /api/*. Disabled when API_KEY is unset.
"""

from __future__ import annotations

import secrets
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import API_KEY


def _extract_presented_key(request: Request) -> str | None:
    direct = request.headers.get("x-api-key")
    if direct and direct.strip():
        return direct.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return None


def _keys_match(expected: str, presented: str | None) -> bool:
    if not presented:
        return False
    try:
        return secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require API key for /api routes when API_KEY is configured."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not API_KEY:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path or ""
        if not path.startswith("/api"):
            return await call_next(request)

        presented = _extract_presented_key(request)
        if not _keys_match(API_KEY, presented):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)
