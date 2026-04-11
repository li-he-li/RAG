"""
Similar Case Search Agent — Executor and Validator.

Wraps existing similar_case_search service into the agent framework
with [Executor -> Validator] pipeline topology.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import (
    ExecutorAgent,
    RawResult,
    ValidatedOutput,
    ValidatorAgent,
)
from app.agents.pipeline import AgentPipeline

# Re-export for test patching — module-level reference that tests can mock
from app.services.similar_case_search import execute_similar_case_search  # noqa: F401

logger = logging.getLogger(__name__)


class SimilarCaseExecutor(ExecutorAgent):
    """Executes similar case search by delegating to existing service."""

    @property
    def name(self) -> str:
        return "similar_case_executor"

    async def can_handle(self, input_data: Any) -> float:
        if isinstance(input_data, dict) and "request" in input_data:
            return 0.9
        return 0.0

    async def validate(self, input_data: Any) -> None:
        if not isinstance(input_data, dict):
            return
        # Basic input shape check — request must be present
        if "request" not in input_data:
            return

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        try:
            from app.models.schemas import SimilarCaseSearchRequest

            request_data = input_data.get("request", {})
            db = input_data.get("db")

            # Build typed request if needed
            if isinstance(request_data, dict):
                request = SimilarCaseSearchRequest(**request_data)
            else:
                request = request_data

            if db is None:
                return RawResult(
                    status="error",
                    output=None,
                    error="database session required",
                )

            response = await execute_similar_case_search(request, db)
            # Convert Pydantic model to dict for agent framework
            output = response.model_dump() if hasattr(response, "model_dump") else response

            return RawResult(
                status="success",
                output=output,
            )

        except Exception as exc:
            logger.exception("SimilarCaseExecutor failed: %s", exc)
            return RawResult(
                status="error",
                output=None,
                error=str(exc),
            )


class SimilarCaseValidator(ValidatorAgent):
    """Validates similar case search results for completeness."""

    @property
    def name(self) -> str:
        return "similar_case_validator"

    async def can_handle(self, input_data: Any) -> float:
        if isinstance(input_data, RawResult):
            return 0.8
        return 0.0

    async def validate(self, input_data: Any) -> None:
        pass  # Accept any input

    async def run(self, raw_result: RawResult) -> ValidatedOutput:
        # Error results pass through with metadata
        if raw_result.status == "error":
            return ValidatedOutput(
                output=raw_result.output,
                schema_name="SimilarCaseSearchResponse",
                metadata={"error": raw_result.error},
            )

        output = raw_result.output or {}

        # Validate response has required top-level keys
        required_keys = {"case_search_profile", "comparison_query"}
        missing = required_keys - set(output.keys()) if isinstance(output, dict) else required_keys
        metadata: dict[str, Any] = {}

        if missing:
            metadata["missing_fields"] = list(missing)

        # Check match counts
        if isinstance(output, dict):
            similar = output.get("similar_case_matches", [])
            near_dup = output.get("near_duplicate_matches", [])
            exact = output.get("exact_match")
            metadata["match_counts"] = {
                "exact": 1 if exact else 0,
                "near_duplicate": len(near_dup),
                "similar": len(similar),
            }

        return ValidatedOutput(
            output=output,
            schema_name="SimilarCaseSearchResponse",
            metadata=metadata,
        )


def create_similar_case_pipeline(
    trajectory_logger: Any | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> AgentPipeline:
    """Create a [Executor -> Validator] pipeline for similar case search."""
    return AgentPipeline(
        executor=SimilarCaseExecutor(),
        validator=SimilarCaseValidator(),
        trajectory_logger=trajectory_logger,
        prompt_versions=prompt_versions,
    )
