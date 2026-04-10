from __future__ import annotations

from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.analytics.telemetry import TelemetryService

CORRELATION_ID_HEADER = "x-correlation-id"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a request-scoped correlation ID to telemetry and responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        telemetry = TelemetryService.instance()
        incoming_id = request.headers.get(CORRELATION_ID_HEADER)
        with telemetry.correlation_context(incoming_id) as correlation_id:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            return response
