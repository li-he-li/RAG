"""
Trajectory storage layer — in-memory implementation for testing and development.
PostgreSQL-backed implementation can be swapped in via the TrajectoryStore protocol.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class TrajectoryStore(Protocol):
    """Protocol for trajectory storage backends."""

    def save(
        self,
        session_id: str,
        agent_name: str,
        step_type: str,
        input_hash: str,
        output: Any,
        duration_ms: float,
        token_usage: dict[str, int] | None = None,
        prompt_versions: dict[str, str] | None = None,
    ) -> None: ...

    def query_by_session(self, session_id: str) -> list[dict[str, Any]]: ...

    def cleanup_expired(self, ttl_days: int = 30) -> int: ...


class InMemoryTrajectoryStore:
    """In-memory trajectory store for testing and single-process deployment."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def save(
        self,
        session_id: str,
        agent_name: str,
        step_type: str,
        input_hash: str,
        output: Any,
        duration_ms: float,
        token_usage: dict[str, int] | None = None,
        prompt_versions: dict[str, str] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "session_id": session_id,
            "agent_name": agent_name,
            "step_type": step_type,
            "input_hash": input_hash,
            "output": output,
            "duration_ms": float(duration_ms),
            "token_usage": dict(token_usage) if token_usage else None,
            "prompt_versions": dict(prompt_versions) if prompt_versions else None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._records.append(record)

    def query_by_session(self, session_id: str) -> list[dict[str, Any]]:
        return [r for r in self._records if r["session_id"] == session_id]

    def cleanup_expired(self, ttl_days: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        original = len(self._records)
        self._records = [
            r for r in self._records
            if datetime.fromisoformat(r["created_at"]) > cutoff
        ]
        return original - len(self._records)

    @property
    def records(self) -> list[dict[str, Any]]:
        return self._records
