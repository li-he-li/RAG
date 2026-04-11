"""
Contract Review Agent — Planner, Executor, Validator.

Wraps existing contract_review service into the agent framework
with [Planner -> Executor -> Validator] pipeline topology.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
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
from app.agents.output_governance import GovernanceBlockError, SchemaValidationError
from app.agents.pipeline import AgentPipeline
from app.utils.streaming import encode_stream_event

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

    @staticmethod
    def _resolve_input(input_data: ExecutionPlan | dict[str, Any]) -> dict[str, Any]:
        if isinstance(input_data, ExecutionPlan):
            if not input_data.steps:
                return {}
            return dict(input_data.steps[0].input_mapping)
        return input_data

    async def run(self, input_data: ExecutionPlan | dict[str, Any]) -> RawResult:
        try:
            resolved_input = self._resolve_input(input_data)
            session_id = resolved_input.get("session_id", "")
            template_id = resolved_input.get("template_id", "")
            db = resolved_input.get("db")

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

    async def stream(self, input_data: ExecutionPlan | dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        resolved_input = self._resolve_input(input_data)
        session_id = resolved_input.get("session_id", "")
        template_id = resolved_input.get("template_id", "")
        query = resolved_input.get("query", "")
        db = resolved_input.get("db")

        if not session_id or not template_id or db is None:
            yield {"type": "error", "detail": "session_id, template_id, and db are required"}
            return

        async for line in stream_template_difference_review(
            session_id=session_id,
            template_id=template_id,
            query=query,
            db=db,
        ):
            if not line.strip():
                continue
            yield json.loads(line)


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


async def stream_contract_review_pipeline(
    input_data: dict[str, Any],
    *,
    trajectory_logger: Any | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """Stream contract review while validating post-stream summaries."""
    pipeline = create_contract_review_pipeline(
        trajectory_logger=trajectory_logger,
        prompt_versions=prompt_versions,
    )
    planner = pipeline.planner
    executor = pipeline.executor
    validator = pipeline.validator
    assert planner is not None
    assert validator is not None

    plan_started = time.monotonic()
    execution_plan = await planner.execute(input_data)
    pipeline._record_trajectory(planner, "plan", input_data, execution_plan, plan_started)

    execute_started = time.monotonic()
    file_summaries: dict[str, dict[str, Any]] = {}
    final_answer = ""

    try:
        async for event in executor.stream(execution_plan):
            event_type = event.get("type")
            if event_type == "file_done":
                file_id = str(event.get("file_id", ""))
                file_summaries[file_id] = {
                    "file_id": file_id,
                    "file_name": event.get("file_name", ""),
                    "template_id": event.get("template_id", ""),
                    "template_name": event.get("template_name", ""),
                    "findings": [{} for _ in range(int(event.get("finding_count", 0) or 0))],
                    "review_markdown": "",
                }
            elif event_type == "done":
                final_answer = str(event.get("answer", "") or "")
            elif event_type == "error":
                raw_error = RawResult(status="error", output=None, error=str(event.get("detail", "internal_error")))
                pipeline._record_trajectory(executor, "execute", execution_plan, raw_error, execute_started)
                yield encode_stream_event(event)
                return

            yield encode_stream_event(event)

        summarized_output = list(file_summaries.values())
        if final_answer and summarized_output:
            for item in summarized_output:
                item["review_markdown"] = final_answer

        raw_result = RawResult(status="success", output=summarized_output)
        pipeline._record_trajectory(executor, "execute", execution_plan, raw_result, execute_started)

        validate_started = time.monotonic()
        validated = await validator.execute(raw_result)
        pipeline._record_trajectory(validator, "validate", raw_result, validated, validate_started)

        if validated.metadata.get("error"):
            yield encode_stream_event(
                {
                    "type": "validation_rejected",
                    "agent_name": validator.name,
                    "payload": {"reasons": [validated.metadata["error"]]},
                }
            )
            return

        await pipeline.governance_pipeline.govern_output(validated, layer="post_stream")
    except (GovernanceBlockError, SchemaValidationError) as exc:
        yield pipeline.governance_pipeline.retracted_event(
            violated_rule=exc.violated_rule,
            message="discard prior streamed content",
        )
    except Exception as exc:
        logger.exception("stream_contract_review_pipeline failed: %s", exc)
        detail = str(exc) if str(exc) else "internal server error"
        yield encode_stream_event({"type": "error", "detail": detail})
