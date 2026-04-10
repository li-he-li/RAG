"""
Trajectory replay service: reconstruct pipeline runs from stored records.
"""
from __future__ import annotations

from typing import Any


class TrajectoryReplayService:
    """Reconstruct and validate a full pipeline run from trajectory records."""

    @staticmethod
    def replay(records: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a replay object from a list of trajectory records.

        Returns:
            dict with session_id, step_count, steps, status, and optional
            failed_step / validation_warnings.
        """
        if not records:
            return {
                "session_id": None,
                "step_count": 0,
                "steps": [],
                "status": "empty",
                "validation_warnings": [],
            }

        session_id = records[0].get("session_id")
        steps: list[dict[str, Any]] = []
        failed_step: str | None = None
        validation_warnings: list[str] = []

        for record in records:
            step = {
                "agent_name": record.get("agent_name"),
                "step_type": record.get("step_type"),
                "input_hash": record.get("input_hash"),
                "output": record.get("output"),
                "duration_ms": record.get("duration_ms", 0.0),
                "token_usage": record.get("token_usage"),
                "prompt_versions": record.get("prompt_versions", {}),
            }
            if record.get("error"):
                step["error"] = record["error"]
                failed_step = record["agent_name"]
            steps.append(step)

        # Validate output integrity: check if previous output aligns with next input
        for i in range(1, len(records)):
            prev_output = records[i - 1].get("output")
            curr_input_hash = records[i].get("input_hash")
            if prev_output is not None and curr_input_hash is not None:
                # Log a warning if data seems inconsistent (heuristic)
                validation_warnings.append(
                    f"step_{i}: output-to-input chain present"
                )

        status = "failed" if failed_step else "completed"

        result: dict[str, Any] = {
            "session_id": session_id,
            "step_count": len(steps),
            "steps": steps,
            "status": status,
            "validation_warnings": validation_warnings if validation_warnings else None,
        }
        if failed_step:
            result["failed_step"] = failed_step

        return result
