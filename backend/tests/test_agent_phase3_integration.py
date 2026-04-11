"""
Phase 3 end-to-end integration tests for all migrated agent domains.

Exercises the HTTP layer and verifies that each domain route still honors
the legacy public contract after migrating to the agent pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_contract" / "legacy_contracts.json"


def _fixture_contract(endpoint: str) -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return next(contract for contract in fixture["contracts"] if contract["endpoint"] == endpoint)


def _minimal_app() -> FastAPI:
    from app.core.database import get_session
    from app.routers.prediction import router as prediction_router
    from app.routers.search import router as search_router

    app = FastAPI()
    app.dependency_overrides[get_session] = lambda: MagicMock()
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(prediction_router, prefix="/api/v1")
    return app


async def _streaming_events(events: list[dict[str, Any]]) -> Any:
    for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"


class TestPhase3IntegratedRoutes:
    def test_similar_case_route_preserves_legacy_json_contract(self) -> None:
        client = TestClient(_minimal_app())
        expected = _fixture_contract("/api/v1/similar-cases/compare")["response"]

        with patch("app.routers.search._ensure_retrieval_ready", return_value=None), patch(
            "app.agents.similar_case.execute_similar_case_search",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            response = client.post(
                "/api/v1/similar-cases/compare",
                json={
                    "session_id": expected["session_id"],
                    "query": expected["query"],
                    "top_k_documents": 5,
                    "top_k_paragraphs": 3,
                },
            )

        assert response.status_code == 200
        assert response.json() == expected

    def test_contract_review_stream_route_preserves_legacy_event_contract(self) -> None:
        client = TestClient(_minimal_app())
        contract = _fixture_contract("/api/v1/contract-review/stream")

        with patch("app.agents.contract_review.stream_template_difference_review", return_value=_streaming_events(contract["stream_events"])):
            response = client.post(
                "/api/v1/contract-review/stream",
                json={
                    "session_id": "session-contract-001",
                    "template_id": "template-001",
                    "query": contract["stream_events"][0]["query"],
                },
            )

        assert response.status_code == 200
        decoded = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert [event["type"] for event in decoded] == contract["expected_event_types"]
        assert decoded == contract["stream_events"]

    def test_chat_stream_route_preserves_legacy_event_contract(self) -> None:
        client = TestClient(_minimal_app())
        contract = _fixture_contract("/api/v1/chat/stream")

        with patch("app.routers.search._ensure_retrieval_ready", return_value=None), patch(
            "app.agents.chat.stream_chat_pipeline",
            return_value=_streaming_events(contract["stream_events"]),
        ):
            response = client.post(
                "/api/v1/chat/stream",
                json={
                    "query": contract["stream_events"][0]["query"],
                    "session_id": "session-contract-001",
                    "use_chat_attachment": False,
                    "top_k_documents": 3,
                    "top_k_paragraphs": 8,
                },
            )

        assert response.status_code == 200
        decoded = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        assert decoded == contract["stream_events"]

    def test_opponent_prediction_route_preserves_legacy_json_contract(self) -> None:
        from app.models.schemas import OpponentPredictionReport

        client = TestClient(_minimal_app())
        expected = _fixture_contract("/api/v1/opponent-prediction/start")["response"]
        report = OpponentPredictionReport.model_validate(expected)

        with patch(
            "app.agents.opponent_prediction.build_prediction_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = client.post(
                "/api/v1/opponent-prediction/start",
                json={
                    "session_id": expected["session_id"],
                    "template_id": expected["template_id"],
                    "query": expected["query"],
                },
            )

        assert response.status_code == 200
        assert response.json() == expected
