from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from app.agents import RawResult, Rejection, ValidatedOutput
from app.agents.compatibility import CompatibilityAdapter, EndpointContract, ErrorEnvelope
from app.agents.output_governance import GovernanceBlockError


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _chat_response_mapper(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": output["query"],
        "answer": output["answer"],
        "citations": output.get("citations", []),
        "grounded": output.get("grounded", False),
        "used_documents": output.get("used_documents", 0),
        "attachment_used": output.get("attachment_used", False),
        "attachment_file_name": output.get("attachment_file_name"),
    }


def _adapter() -> CompatibilityAdapter:
    return CompatibilityAdapter(
        EndpointContract(
            name="chat",
            response_mapper=_chat_response_mapper,
            public_stream_event_types=frozenset({"start", "delta", "done", "error"}),
        )
    )


async def _events(lines: list[dict[str, Any] | str]) -> AsyncIterator[str]:
    for line in lines:
        if isinstance(line, str):
            yield line
        else:
            yield json.dumps(line, ensure_ascii=False) + "\n"


async def _collect_stream(
    adapter: CompatibilityAdapter,
    lines: list[dict[str, Any] | str],
) -> list[dict[str, Any]]:
    return [json.loads(line) async for line in adapter.adapt_stream(_events(lines))]


def test_non_streaming_endpoint_preserves_legacy_response_shape() -> None:
    adapter = _adapter()
    internal_result = ValidatedOutput(
        output={
            "query": "contract risk",
            "answer": "legacy answer",
            "citations": [{"doc_id": "doc-1"}],
            "grounded": True,
            "used_documents": 1,
            "attachment_used": False,
            "attachment_file_name": None,
            "agent_trace": {"internal": "must not leak"},
        },
        schema_name="ChatResponse",
    )

    response = adapter.adapt_response(internal_result)

    assert response == {
        "query": "contract risk",
        "answer": "legacy answer",
        "citations": [{"doc_id": "doc-1"}],
        "grounded": True,
        "used_documents": 1,
        "attachment_used": False,
        "attachment_file_name": None,
    }
    assert "agent_trace" not in response


def test_raw_result_can_be_mapped_to_legacy_response_shape() -> None:
    adapter = _adapter()
    raw_result = RawResult(
        status="success",
        output={
            "query": "contract risk",
            "answer": "raw answer",
            "citations": [],
            "internal_steps": ["executor"],
        },
    )

    response = adapter.adapt_response(raw_result)

    assert response["answer"] == "raw answer"
    assert "internal_steps" not in response


def test_streaming_endpoint_suppresses_internal_agent_events() -> None:
    adapter = _adapter()

    public_events = _run(
        _collect_stream(
            adapter,
            [
                {"type": "step_started", "agent_name": "planner", "payload": {}},
                {"type": "plan_created", "agent_name": "planner", "payload": {"step_count": 2}},
                {"type": "start", "query": "contract risk", "grounded": True},
                {"type": "delta", "delta": "hello"},
                {"type": "validation_passed", "agent_name": "validator", "payload": {}},
                {"type": "done", "query": "contract risk", "answer": "hello"},
                {"type": "pipeline_completed", "agent_name": "validator", "payload": {}},
            ],
        )
    )

    assert [event["type"] for event in public_events] == ["start", "delta", "done"]
    assert all("agent_name" not in event for event in public_events)


def test_streaming_governance_and_rejection_events_map_to_legacy_error_event() -> None:
    adapter = _adapter()

    public_events = _run(
        _collect_stream(
            adapter,
            [
                {"type": "start", "query": "contract risk"},
                {
                    "type": "governance_retracted",
                    "agent_name": "output_governance",
                    "payload": {
                        "violated_rule": "pii.ssn",
                        "message": "discard prior streamed content",
                    },
                },
                {
                    "type": "validation_rejected",
                    "agent_name": "validator",
                    "payload": {"reasons": ["missing citation"]},
                },
            ],
        )
    )

    assert public_events == [
        {"type": "start", "query": "contract risk"},
        {"type": "error", "detail": "Response was blocked by governance."},
        {"type": "error", "detail": "Agent validation rejected the response."},
    ]
    assert "pii.ssn" not in json.dumps(public_events)


def test_adapter_preserves_legacy_error_payload_shape_and_status_codes() -> None:
    adapter = _adapter()

    rejection = adapter.adapt_error(Rejection(reasons=("missing citation",)))
    governance = adapter.adapt_error(
        GovernanceBlockError(
            "blocked",
            violated_rule="pii.ssn",
            rule_pattern_matched="secret-pattern",
        )
    )
    timeout = adapter.adapt_error(TimeoutError("llm timeout"))
    failure = adapter.adapt_error(RuntimeError("database path leaked"))

    assert rejection == ErrorEnvelope(
        status_code=422,
        payload={
            "error": "validation_rejected",
            "detail": "Agent validation rejected the response.",
            "citation_missing": False,
        },
    )
    assert governance == ErrorEnvelope(
        status_code=403,
        payload={
            "error": "governance_blocked",
            "detail": "Response was blocked by governance.",
            "citation_missing": False,
        },
    )
    assert timeout.status_code == 504
    assert timeout.payload["error"] == "timeout"
    assert failure.status_code == 500
    assert failure.payload["detail"] != "database path leaked"
