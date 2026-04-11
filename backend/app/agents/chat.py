"""
Chat Agent - Executor and Validator.

Wraps the existing grounded chat service into the agent framework
with [Executor -> Validator] pipeline topology.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app.agents.base import ExecutorAgent, RawResult, ValidatedOutput, ValidatorAgent
from app.agents.output_governance import GovernanceBlockError, SchemaValidationError
from app.agents.pipeline import AgentPipeline
from app.models.schemas import ChatRequest, ChatResponse
from app.utils.streaming import encode_stream_event

# Re-export for test patching
from app.services.chat import execute_grounded_chat, stream_grounded_chat  # noqa: F401

logger = logging.getLogger(__name__)


class ChatExecutor(ExecutorAgent):
    """Executes grounded chat by delegating to the existing service."""

    @property
    def name(self) -> str:
        return "chat_executor"

    async def validate(self, input_data: Any) -> None:
        pass

    @staticmethod
    def _resolve_input(input_data: dict[str, Any]) -> tuple[ChatRequest, Any]:
        request_data = input_data.get("request", {})
        db = input_data.get("db")
        request = request_data if isinstance(request_data, ChatRequest) else ChatRequest(**request_data)
        return request, db

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        try:
            request, db = self._resolve_input(input_data)
            if db is None:
                return RawResult(status="error", output=None, error="database session required")

            response = await execute_grounded_chat(request, db)
            output = response.model_dump(mode="json") if hasattr(response, "model_dump") else response
            return RawResult(status="success", output=output)
        except Exception as exc:
            logger.exception("ChatExecutor failed: %s", exc)
            return RawResult(status="error", output=None, error=str(exc))

    async def stream(self, input_data: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        request, db = self._resolve_input(input_data)
        if db is None:
            yield {"type": "error", "detail": "database session required"}
            return

        async for line in stream_grounded_chat(request, db):
            if not line.strip():
                continue
            yield json.loads(line)


class ChatValidator(ValidatorAgent):
    """Validates grounded chat results for contract compliance."""

    @property
    def name(self) -> str:
        return "chat_validator"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, raw_result: RawResult) -> ValidatedOutput:
        if raw_result.status == "error":
            return ValidatedOutput(
                output=raw_result.output,
                schema_name="ChatResponse",
                metadata={"error": raw_result.error},
            )

        validated = ChatResponse.model_validate(raw_result.output or {})
        output = validated.model_dump(mode="json")
        return ValidatedOutput(
            output=output,
            schema_name="ChatResponse",
            metadata={
                "schema_model": ChatResponse,
                "citation_count": len(validated.citations),
                "grounded": validated.grounded,
                "used_documents": validated.used_documents,
            },
        )


def create_chat_pipeline(
    trajectory_logger: Any | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> AgentPipeline:
    """Create a [Executor -> Validator] pipeline for grounded chat."""
    return AgentPipeline(
        executor=ChatExecutor(),
        validator=ChatValidator(),
        trajectory_logger=trajectory_logger,
        prompt_versions=prompt_versions,
    )


async def stream_chat_pipeline(
    input_data: dict[str, Any],
    *,
    trajectory_logger: Any | None = None,
    prompt_versions: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """Stream grounded chat while validating the final public contract."""
    pipeline = create_chat_pipeline(
        trajectory_logger=trajectory_logger,
        prompt_versions=prompt_versions,
    )
    executor = pipeline.executor
    validator = pipeline.validator
    assert validator is not None

    start_time = time.monotonic()
    final_done_event: dict[str, Any] | None = None
    raw_result: RawResult | None = None

    try:
        async for event in executor.stream(input_data):
            event_type = event.get("type")
            if event_type == "done":
                done_payload = {key: value for key, value in event.items() if key != "type"}
                raw_result = RawResult(status="success", output=done_payload)
                final_done_event = done_payload
                continue

            if event_type == "error":
                raw_result = RawResult(status="error", output=None, error=str(event.get("detail", "internal_error")))
                yield encode_stream_event(event)
                return

            yield encode_stream_event(event)

        if raw_result is None:
            raw_result = RawResult(status="error", output=None, error="chat stream ended without done event")

        pipeline._record_trajectory(executor, "execute", input_data, raw_result, start_time)

        validation_started = time.monotonic()
        validated = await validator.execute(raw_result)
        pipeline._record_trajectory(validator, "validate", raw_result, validated, validation_started)

        if validated.metadata.get("error"):
            yield encode_stream_event(
                {
                    "type": "validation_rejected",
                    "agent_name": validator.name,
                    "payload": {"reasons": [validated.metadata["error"]]},
                }
            )
            return

        governed = await pipeline.governance_pipeline.govern_output(validated, layer="post_stream")
        yield encode_stream_event({"type": "done", **governed.output})
    except (GovernanceBlockError, SchemaValidationError) as exc:
        yield pipeline.governance_pipeline.retracted_event(
            violated_rule=exc.violated_rule,
            message="discard prior streamed content",
        )
    except Exception as exc:
        logger.exception("stream_chat_pipeline failed: %s", exc)
        detail = str(exc) if str(exc) else "internal server error"
        yield encode_stream_event({"type": "error", "detail": detail})
