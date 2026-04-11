"""
TrajectoryLogger: records agent pipeline steps with data governance.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.trajectory.governance import DataGovernancePolicy, default_governance_policy

logger = logging.getLogger(__name__)


def _serialize_for_hash(data: Any) -> str:
    """Deterministically serialize data for SHA-256 hashing."""
    try:
        return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(data)


def _compute_input_hash(data: Any) -> str:
    """Compute SHA-256 hash of serialized input data."""
    serialized = _serialize_for_hash(data)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _serialize_output(data: Any) -> Any:
    """Serialize output data for storage. Returns JSON-safe representation."""
    if data is None:
        return None
    if isinstance(data, (str, int, float, bool)):
        return data
    try:
        # Test if JSON-serializable
        json.dumps(data, ensure_ascii=False, default=str)
        return data
    except (TypeError, ValueError):
        return str(data)


class TrajectoryLogger:
    """Records trajectory entries for each agent step in a pipeline execution.

    Features:
    - Deterministic input hashing (SHA-256)
    - Data governance with redaction
    - Prompt version snapshot capture
    - Non-blocking in-memory recording
    - TTL-based cleanup
    """

    def __init__(
        self,
        session_id: str,
        governance_policy: DataGovernancePolicy | None = None,
    ) -> None:
        self._session_id = session_id
        self._governance = governance_policy or default_governance_policy()
        self._records: list[dict[str, Any]] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def records(self) -> list[dict[str, Any]]:
        return self._records

    def record(
        self,
        agent_name: str,
        step_type: str,
        input_data: Any,
        output: Any,
        duration_ms: float,
        token_usage: dict[str, int] | None = None,
        prompt_versions: dict[str, str] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Record a single agent step trajectory entry.

        This method never raises — write failures are logged, not propagated.
        """
        try:
            input_hash = _compute_input_hash(input_data)
            serialized_input = _serialize_output(input_data)
            serialized_output = _serialize_output(output)

            # Apply data governance to output
            governed_input = serialized_input
            if isinstance(serialized_input, dict):
                governed_input = self._governance.apply(serialized_input)
            governed_output = serialized_output
            if isinstance(serialized_output, dict):
                governed_output = self._governance.apply(serialized_output)

            record: dict[str, Any] = {
                "session_id": self._session_id,
                "agent_name": agent_name,
                "step_type": step_type,
                "input_hash": input_hash,
                "input_payload": governed_input,
                "output": governed_output,
                "duration_ms": float(duration_ms),
                "token_usage": dict(token_usage) if token_usage else None,
                "prompt_versions": dict(prompt_versions) if prompt_versions else {},
                "created_at": datetime.now(UTC),
            }
            if error:
                record["error"] = error

            self._records.append(record)
            return record

        except Exception as exc:
            logger.warning(
                "TrajectoryLogger.record() swallowed error: %s", exc
            )
            return {
                "session_id": self._session_id,
                "agent_name": agent_name,
                "step_type": step_type,
                "input_hash": "",
                "output": None,
                "duration_ms": 0.0,
                "error": f"recording_failed: {exc}",
            }

    def query(self, session_id: str) -> list[dict[str, Any]]:
        """Query trajectory records by session_id (in-memory)."""
        if session_id != self._session_id:
            return []
        return list(self._records)

    def cleanup_expired(self, ttl_days: int = 30) -> int:
        """Remove records older than ttl_days. Returns count of removed records."""
        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        original_count = len(self._records)
        self._records = [
            r for r in self._records
            if r.get("created_at", datetime.now(UTC)) > cutoff
        ]
        removed = original_count - len(self._records)
        if removed:
            logger.info(
                "Trajectory cleanup: removed %d expired records (TTL=%d days)",
                removed,
                ttl_days,
            )
        return removed
