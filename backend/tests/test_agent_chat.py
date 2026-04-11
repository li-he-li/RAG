"""
Tests for Chat Agent pipeline.

Covers: executor, validator, streaming, API contract compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.base import RawResult, ValidatedOutput


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_contract" / "legacy_contracts.json"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _chat_contract() -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return next(
        contract
        for contract in fixture["contracts"]
        if contract["endpoint"] == "/api/v1/chat/stream"
    )


def _chat_done_payload() -> dict[str, Any]:
    done_event = _chat_contract()["stream_events"][-1]
    return {key: value for key, value in done_event.items() if key != "type"}


def _chat_request_payload() -> dict[str, Any]:
    return {
        "query": "Can the owner claim delay damages?",
        "session_id": "session-contract-001",
        "use_chat_attachment": False,
        "top_k_documents": 3,
        "top_k_paragraphs": 8,
        "dispute_focus": None,
    }


async def _event_generator(events: list[dict[str, Any]]) -> Any:
    for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"


class TestChatExecutor:
    @pytest.mark.anyio
    async def test_executor_returns_raw_result_on_success(self) -> None:
        from app.agents.chat import ChatExecutor
        from app.models.schemas import ChatResponse

        response = ChatResponse.model_validate(_chat_done_payload())

        with patch(
            "app.agents.chat.execute_grounded_chat",
            new_callable=AsyncMock,
            return_value=response,
        ) as mock_execute:
            executor = ChatExecutor()
            result = await executor.run({"request": _chat_request_payload(), "db": MagicMock()})

        mock_execute.assert_called_once()
        assert isinstance(result, RawResult)
        assert result.status == "success"
        assert result.output["answer"] == response.answer

    @pytest.mark.anyio
    async def test_executor_handles_service_error(self) -> None:
        from app.agents.chat import ChatExecutor

        with patch(
            "app.agents.chat.execute_grounded_chat",
            new_callable=AsyncMock,
            side_effect=RuntimeError("chat failed"),
        ):
            executor = ChatExecutor()
            result = await executor.run({"request": _chat_request_payload(), "db": MagicMock()})

        assert isinstance(result, RawResult)
        assert result.status == "error"
        assert "chat failed" in (result.error or "")


class TestChatValidator:
    @pytest.mark.anyio
    async def test_validator_passes_valid_chat_response(self) -> None:
        from app.agents.chat import ChatValidator

        raw = RawResult(status="success", output=_chat_done_payload())
        validator = ChatValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        assert result.schema_name == "ChatResponse"
        assert result.metadata["citation_count"] == 1
        assert result.metadata["grounded"] is True

    @pytest.mark.anyio
    async def test_validator_carries_error_metadata(self) -> None:
        from app.agents.chat import ChatValidator

        raw = RawResult(status="error", output=None, error="service error")
        validator = ChatValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        assert result.metadata["error"] == "service error"


class TestChatPipeline:
    @pytest.mark.anyio
    async def test_pipeline_run_end_to_end(self) -> None:
        from app.agents.chat import create_chat_pipeline
        from app.models.schemas import ChatResponse

        response = ChatResponse.model_validate(_chat_done_payload())

        with patch(
            "app.agents.chat.execute_grounded_chat",
            new_callable=AsyncMock,
            return_value=response,
        ):
            pipeline = create_chat_pipeline()
            result = await pipeline.run({"request": _chat_request_payload(), "db": MagicMock()})

        assert hasattr(result, "output")
        assert result.output["query"] == _chat_request_payload()["query"]

    @pytest.mark.anyio
    async def test_pipeline_records_trajectory(self) -> None:
        from app.agents.chat import create_chat_pipeline
        from app.models.schemas import ChatResponse
        from app.services.trajectory.logger import TrajectoryLogger

        response = ChatResponse.model_validate(_chat_done_payload())

        with patch(
            "app.agents.chat.execute_grounded_chat",
            new_callable=AsyncMock,
            return_value=response,
        ):
            traj = TrajectoryLogger(session_id="sess-chat-traj")
            pipeline = create_chat_pipeline(trajectory_logger=traj)
            await pipeline.run({"request": _chat_request_payload(), "db": MagicMock()})

        agent_names = [record["agent_name"] for record in traj.records]
        assert agent_names == ["chat_executor", "chat_validator"]

    @pytest.mark.anyio
    async def test_stream_chat_pipeline_preserves_legacy_stream_contract(self) -> None:
        from app.agents.chat import stream_chat_pipeline

        stream_events = _chat_contract()["stream_events"]

        with patch(
            "app.agents.chat.stream_grounded_chat",
            return_value=_event_generator(stream_events),
        ):
            lines = [
                line
                async for line in stream_chat_pipeline(
                    {"request": _chat_request_payload(), "db": MagicMock()}
                )
            ]

        decoded = [json.loads(line) for line in lines]
        assert [event["type"] for event in decoded] == ["start", "delta", "done"]
        assert decoded[-1]["answer"] == _chat_done_payload()["answer"]


class TestChatRoute:
    def _create_app(self) -> FastAPI:
        from app.core.database import get_session
        from app.routers.search import router as search_router

        app = FastAPI()
        app.dependency_overrides[get_session] = lambda: MagicMock()
        app.include_router(search_router, prefix="/api/v1")
        return app

    def test_route_filters_internal_events_and_preserves_public_contract(self) -> None:
        client = TestClient(self._create_app())
        lines = [
            {"type": "step_started", "agent_name": "chat_executor", "payload": {}},
            _chat_contract()["stream_events"][0],
            _chat_contract()["stream_events"][1],
            {"type": "validation_passed", "agent_name": "chat_validator", "payload": {}},
            _chat_contract()["stream_events"][2],
        ]

        with patch("app.routers.search._ensure_retrieval_ready", return_value=None), patch(
            "app.agents.chat.stream_chat_pipeline",
            return_value=_event_generator(lines),
        ):
            response = client.post("/api/v1/chat/stream", json=_chat_request_payload())

        assert response.status_code == 200
        decoded = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert [event["type"] for event in decoded] == ["start", "delta", "done"]
        assert all("agent_name" not in event for event in decoded)
