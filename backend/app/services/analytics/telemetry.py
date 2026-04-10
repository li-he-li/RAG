from __future__ import annotations

import json
import logging
import math
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_correlation_id: ContextVar[str | None] = ContextVar(
    "telemetry_correlation_id",
    default=None,
)


class TelemetryService:
    """Centralized structured telemetry for events and lightweight metrics."""

    _instance: TelemetryService | None = None
    _instance_lock = Lock()

    def __init__(self, *, max_buffer_size: int = 1000) -> None:
        self._lock = Lock()
        self._max_buffer_size = max_buffer_size
        self._events: deque[dict[str, Any]] = deque()
        self._latencies: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
        self._token_usage: dict[str, dict[str, int]] = defaultdict(
            lambda: {"prompt": 0, "completion": 0, "total": 0}
        )
        self._outcomes: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0}
        )

    @classmethod
    def instance(cls) -> TelemetryService:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._latencies.clear()
            self._token_usage.clear()
            self._outcomes.clear()
        self.clear_correlation_id()

    def get_correlation_id(self) -> str | None:
        return _correlation_id.get()

    def set_correlation_id(self, correlation_id: str | None = None) -> str:
        resolved = correlation_id or str(uuid.uuid4())
        _correlation_id.set(resolved)
        return resolved

    def clear_correlation_id(self) -> None:
        _correlation_id.set(None)

    @contextmanager
    def correlation_context(self, correlation_id: str | None = None) -> Iterator[str]:
        resolved = correlation_id or str(uuid.uuid4())
        token: Token[str | None] = _correlation_id.set(resolved)
        try:
            yield resolved
        finally:
            _correlation_id.reset(token)

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        agent_name: str | None = None,
        level: int = logging.INFO,
    ) -> dict[str, Any]:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_id": self.get_correlation_id() or self.set_correlation_id(),
            "agent_name": agent_name or (payload or {}).get("agent") or "system",
            "event_type": event_type,
            "payload": dict(payload or {}),
        }
        with self._lock:
            if len(self._events) >= self._max_buffer_size:
                self._events.popleft()
            self._events.append(event)
        logger.log(level, "%s %s", event_type, self.serialize_event(event))
        return event

    def serialize_event(self, event: dict[str, Any]) -> str:
        return json.dumps(event, ensure_ascii=False, sort_keys=True)

    def record_latency(
        self,
        metric_name: str,
        duration_ms: float,
        *,
        agent_name: str = "system",
    ) -> None:
        with self._lock:
            self._latencies[metric_name].append(
                (datetime.now(UTC), float(duration_ms), agent_name)
            )

    def get_latency_histogram(self, metric_name: str) -> dict[str, float | int]:
        with self._lock:
            values = sorted(value for _, value, _ in self._latencies.get(metric_name, []))
        return {
            "count": len(values),
            "p50": self._percentile(values, 0.50),
            "p95": self._percentile(values, 0.95),
            "p99": self._percentile(values, 0.99),
        }

    def record_token_usage(
        self,
        metric_name: str,
        *,
        prompt: int,
        completion: int,
        agent_name: str = "system",
    ) -> None:
        del metric_name
        with self._lock:
            usage = self._token_usage[agent_name]
            usage["prompt"] += int(prompt)
            usage["completion"] += int(completion)
            usage["total"] += int(prompt) + int(completion)

    def get_token_usage(self, *, agent_name: str = "system") -> dict[str, int]:
        with self._lock:
            return dict(self._token_usage[agent_name])

    def record_outcome(
        self,
        metric_name: str,
        outcome: str,
        *,
        agent_name: str = "system",
    ) -> None:
        del agent_name
        if outcome not in {"success", "failure"}:
            raise ValueError("outcome must be 'success' or 'failure'")
        with self._lock:
            self._outcomes[metric_name][outcome] += 1

    def get_outcomes(self, metric_name: str) -> dict[str, float | int]:
        with self._lock:
            success = self._outcomes[metric_name]["success"]
            failure = self._outcomes[metric_name]["failure"]
        total = success + failure
        return {
            "success": success,
            "failure": failure,
            "success_rate": success / total if total else 0.0,
        }

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float | int:
        if not values:
            return 0
        index = max(0, math.ceil(percentile * len(values)) - 1)
        value = values[index]
        return int(value) if value.is_integer() else value
