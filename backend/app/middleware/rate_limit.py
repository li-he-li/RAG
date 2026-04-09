"""
Simple per-IP sliding-window rate limit for /api (in-memory; best for single instance).

Uses LRU-style eviction: when the IP table exceeds capacity, only the
oldest-accessed entries are removed instead of clearing the entire table.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import Lock
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_WINDOW_SEC = 60.0
_MAX_IPS = 4096
_EVICT_BATCH = 256  # number of oldest entries to drop when over capacity


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, per_minute: int) -> None:
        super().__init__(app)
        self._per_minute = per_minute
        self._hits: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = Lock()

    def _evict_oldest(self) -> None:
        """Drop the oldest _EVICT_BATCH entries. Caller must hold self._lock."""
        for _ in range(min(_EVICT_BATCH, len(self._hits))):
            self._hits.popitem(last=False)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._per_minute <= 0:
            return await call_next(request)
        path = request.url.path or ""
        if not path.startswith("/api"):
            return await call_next(request)

        client = request.client
        host = client.host if client else "unknown"
        now = time.monotonic()
        cutoff = now - _WINDOW_SEC

        with self._lock:
            # Evict oldest batch when table is too large
            if len(self._hits) > _MAX_IPS:
                self._evict_oldest()

            stamps = self._hits.get(host)
            if stamps is not None:
                stamps[:] = [t for t in stamps if t > cutoff]
                # Move to end (most recently accessed)
                self._hits.move_to_end(host)
            else:
                stamps = []
                self._hits[host] = stamps

            if len(stamps) >= self._per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试。"},
                )
            stamps.append(now)

        return await call_next(request)
