"""
Contract Review Agent — Planner, Executor, Validator.

Wraps existing contract_review service into the agent framework
with [Planner -> Executor -> Validator] pipeline topology.
"""
from __future__ import annotations

import logging
from typing import Any

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

# Re-export for test patching
from app.services.contract_review import (  # noqa: F401
    generate_template_difference_review,
    stream_template_difference_review,
)

logger = logging.getLogger(__name__)


class ContractReviewPlanner(PlannerAgent):
    """Creates execution plan for contract review: extracts session/template context."""

    @property
    def name(self) -> str:
        return "contract_review_planner"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> ExecutionPlan:
        # Pass through the input data as the execution plan
        return ExecutionPlan(
            steps=(
                PlanStep(
                    name="contract_review",
                    target_agent="contract_review_executor",
                    input_mapping={
                        "session_id": input_data.get("session_id", ""),
                        "template_id": input_data.get("template_id", ""),
                        "query": input_data.get("query", ""),
                        "db": input_data.get("db"),
                    },
                ),
            ),
        )


class ContractReviewExecutor(ExecutorAgent):
    """Executes contract review by delegating to existing service."""

    @property
    def name(self) -> str:
        return "contract_review_executor"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        try:
            session_id = input_data.get("session_id", "")
            template_id = input_data.get("template_id", "")
            db = input_data.get("db")

            if not session_id or not template_id or db is None:
                return RawResult(
                    status="error",
                    output=None,
                    error="session_id, template_id, and db are required",
                )

            results = await generate_template_difference_review(
                session_id=session_id,
                template_id=template_id,
                db=db,
            )

            # Serialize results
            output = []
            for r in results:
                if hasattr(r, "model_dump"):
                    output.append(r.model_dump())
                else:
                    output.append({
                        "file_id": getattr(r, "file_id", ""),
                        "file_name": getattr(r, "file_name", ""),
                        "template_id": getattr(r, "template_id", ""),
                        "template_name": getattr(r, "template_name", ""),
                        "findings": [],
                        "review_markdown": getattr(r, "review_markdown", ""),
                    })

            return RawResult(status="success", output=output)

        except Exception as exc:
            logger.exception("ContractReviewExecutor failed: %s", exc)
            return RawResult(status="error", output=None, error=str(exc))


class ContractReviewValidator(ValidatorAgent):
    """Validates contract review findings for completeness and consistency."""

    @property
    def name(self) -> str:
        return "contract_review_validator"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, raw_result: RawResult) -> ValidatedOutput:
        if raw_result.status == "error":
            return ValidatedOutput(
                output=raw_result.output,
                schema_name="ContractReviewResponse",
                metadata={"error": raw_result.error},
            )

        output = raw_result.output or []
        metadata: dict[str, Any] = {}

        if isinstance(output, list):
            total_findings = sum(
                len(r.get("findings", [])) if isinstance(r, dict) else 0
                for r in output
            )
            metadata["file_count"] = len(output)
            metadata["total_findings"] = total_findings

        return ValidatedOutput(
            output=output,
            schema_name="ContractReviewResponse",
            metadata=metadata,
        )


def create_contract_review_pipeline(
    trajectory_logger: Any | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> AgentPipeline:
    """Create a [Planner -> Executor -> Validator] pipeline for contract review."""
    return AgentPipeline(
        planner=ContractReviewPlanner(),
        executor=ContractReviewExecutor(),
        validator=ContractReviewValidator(),
        trajectory_logger=trajectory_logger,
        prompt_versions=prompt_versions,
    )
