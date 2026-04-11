"""
Opponent Prediction Agent - Planner, Executor, Validator.

Wraps the existing opponent prediction service into the agent framework
with [Planner -> Executor -> Validator] pipeline topology.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.agents.base import (
    ExecutionPlan,
    ExecutorAgent,
    PlanStep,
    PlannerAgent,
    RawResult,
    ValidatedOutput,
    ValidatorAgent,
)
from app.agents.pipeline import AgentPipeline
from app.models.schemas import OpponentPredictionReport

# Re-export for test patching
from app.services.opponent_prediction import build_prediction_report  # noqa: F401

logger = logging.getLogger(__name__)


class PredictionPlanner(PlannerAgent):
    """Builds a single-step execution plan for opponent prediction."""

    @property
    def name(self) -> str:
        return "prediction_planner"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> ExecutionPlan:
        return ExecutionPlan(
            steps=(
                PlanStep(
                    name="opponent_prediction",
                    target_agent="prediction_executor",
                    input_mapping={
                        "session_id": input_data.get("session_id", ""),
                        "template_id": input_data.get("template_id", ""),
                        "query": input_data.get("query", ""),
                        "db": input_data.get("db"),
                    },
                    expected_output_type="OpponentPredictionReport",
                ),
            )
        )


class PredictionExecutor(ExecutorAgent):
    """Executes opponent prediction by delegating to the existing service."""

    @property
    def name(self) -> str:
        return "prediction_executor"

    async def validate(self, input_data: Any) -> None:
        pass

    @staticmethod
    def _resolve_input(input_data: ExecutionPlan | dict[str, Any]) -> dict[str, Any]:
        if isinstance(input_data, ExecutionPlan):
            if not input_data.steps:
                return {}
            return dict(input_data.steps[0].input_mapping)
        return input_data

    async def run(self, input_data: ExecutionPlan | dict[str, Any]) -> RawResult:
        resolved_input = self._resolve_input(input_data)
        session_id = str(resolved_input.get("session_id", "")).strip()
        template_id = str(resolved_input.get("template_id", "")).strip()
        query = str(resolved_input.get("query", "")).strip()
        db = resolved_input.get("db")

        if not session_id or not template_id or not query or db is None:
            return RawResult(
                status="error",
                output={"status_code": 400, "detail": "session_id, template_id, query, and db are required"},
                error="invalid_input",
            )

        try:
            response = await build_prediction_report(
                db,
                session_id=session_id,
                template_id=template_id,
                query=query,
            )
            output = (
                response.model_dump(mode="json")
                if hasattr(response, "model_dump")
                else response
            )
            return RawResult(status="success", output=output)
        except HTTPException as exc:
            return RawResult(
                status="error",
                output={"status_code": exc.status_code, "detail": exc.detail},
                error=str(exc.detail),
            )
        except Exception as exc:
            logger.exception("PredictionExecutor failed: %s", exc)
            return RawResult(
                status="error",
                output={"status_code": 500, "detail": str(exc)},
                error=str(exc),
            )


class PredictionValidator(ValidatorAgent):
    """Validates opponent prediction reports for completeness."""

    @property
    def name(self) -> str:
        return "prediction_validator"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, raw_result: RawResult) -> ValidatedOutput:
        if raw_result.status == "error":
            metadata = {"error": raw_result.error}
            if isinstance(raw_result.output, dict):
                if "status_code" in raw_result.output:
                    metadata["status_code"] = raw_result.output["status_code"]
                if "detail" in raw_result.output:
                    metadata["detail"] = raw_result.output["detail"]
            return ValidatedOutput(
                output=raw_result.output,
                schema_name="OpponentPredictionReport",
                metadata=metadata,
            )

        validated = OpponentPredictionReport.model_validate(raw_result.output or {})
        output = validated.model_dump(mode="json")
        metadata = {
            "schema_model": OpponentPredictionReport,
            "predicted_argument_count": len(validated.predicted_arguments),
            "evidence_count": validated.evidence_count,
            "inference_count": validated.inference_count,
        }
        return ValidatedOutput(
            output=output,
            schema_name="OpponentPredictionReport",
            metadata=metadata,
        )


def create_opponent_prediction_pipeline(
    trajectory_logger: Any | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> AgentPipeline:
    """Create a [Planner -> Executor -> Validator] pipeline for opponent prediction."""
    return AgentPipeline(
        planner=PredictionPlanner(),
        executor=PredictionExecutor(),
        validator=PredictionValidator(),
        trajectory_logger=trajectory_logger,
        prompt_versions=prompt_versions,
    )
