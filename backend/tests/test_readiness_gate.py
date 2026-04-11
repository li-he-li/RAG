from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _chat_request_payload() -> dict[str, object]:
    return {
        "query": "Can the owner claim delay damages?",
        "session_id": "session-readiness-001",
        "use_chat_attachment": False,
        "top_k_documents": 3,
        "top_k_paragraphs": 8,
        "dispute_focus": None,
    }


async def _event_generator(events: list[dict[str, object]]):
    for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"


def _minimal_app() -> FastAPI:
    from app.core.database import get_session
    from app.routers.search import router as search_router

    app = FastAPI()
    app.dependency_overrides[get_session] = lambda: MagicMock()
    app.include_router(search_router, prefix="/api/v1")
    return app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TestReadinessProbe:
    def test_probe_bootstrap_status_refreshes_snapshot(self) -> None:
        from app.core import config

        original_status = config.get_bootstrap_status()
        try:
            with patch("app.core.config._probe_postgresql_readiness", return_value=True), patch(
                "app.core.config._probe_qdrant_readiness",
                return_value=True,
            ), patch(
                "app.core.config._probe_embedding_model_readiness",
                return_value=True,
            ), patch(
                "app.core.config._probe_reranker_model_readiness",
                return_value=True,
            ):
                status = config.probe_bootstrap_status(refresh_snapshot=True)

            assert status["all_ready"] is True
            assert config.get_bootstrap_status()["all_ready"] is True
            assert config.get_bootstrap_missing_components(status) == []
        finally:
            config._BOOTSTRAP_STATUS = original_status


class TestRetrievalGate:
    def test_gate_uses_live_probe_when_bootstrap_snapshot_is_stale(self) -> None:
        from app.core import config
        from app.routers.search import _ensure_retrieval_ready

        original_status = config.get_bootstrap_status()
        config._BOOTSTRAP_STATUS = {
            "postgresql_ready": False,
            "qdrant_ready": False,
            "embedding_model_ready": False,
            "reranker_model_ready": False,
            "all_ready": False,
        }
        try:
            live_ready = {
                "postgresql_ready": True,
                "qdrant_ready": True,
                "embedding_model_ready": True,
                "reranker_model_ready": True,
                "all_ready": True,
            }
            with patch("app.routers.search.probe_bootstrap_status", return_value=live_ready) as mock_probe:
                _ensure_retrieval_ready()

            mock_probe.assert_called_once_with(refresh_snapshot=True)
        finally:
            config._BOOTSTRAP_STATUS = original_status

    def test_gate_reports_live_missing_components(self) -> None:
        from app.routers.search import _ensure_retrieval_ready

        live_status = {
            "postgresql_ready": True,
            "qdrant_ready": True,
            "embedding_model_ready": False,
            "reranker_model_ready": True,
            "all_ready": False,
        }
        with patch("app.routers.search.probe_bootstrap_status", return_value=live_status):
            with pytest.raises(HTTPException) as excinfo:
                _ensure_retrieval_ready()

        assert excinfo.value.status_code == 503
        assert "Embedding Model" in excinfo.value.detail

    def test_health_and_chat_stream_share_same_live_readiness_source(self) -> None:
        client = TestClient(_minimal_app())
        ready_status = {
            "postgresql_ready": True,
            "qdrant_ready": True,
            "embedding_model_ready": True,
            "reranker_model_ready": True,
            "all_ready": True,
        }
        stream_events = [
            {"type": "start", "query": _chat_request_payload()["query"]},
            {"type": "delta", "delta": "grounded answer"},
            {
                "type": "done",
                "query": _chat_request_payload()["query"],
                "answer": "grounded answer",
                "citations": [],
                "grounded": True,
                "used_documents": 1,
                "attachment_used": False,
                "attachment_file_name": None,
                "timestamp": "2026-04-11T00:00:00Z",
            },
        ]

        with patch("app.routers.search.probe_bootstrap_status", return_value=ready_status), patch(
            "app.agents.chat.stream_chat_pipeline",
            return_value=_event_generator(stream_events),
        ):
            health_response = client.get("/api/v1/health")
            chat_response = client.post("/api/v1/chat/stream", json=_chat_request_payload())

        assert health_response.status_code == 200
        assert health_response.json()["all_ready"] is True
        assert chat_response.status_code == 200
        decoded = [json.loads(line) for line in chat_response.text.splitlines() if line.strip()]
        assert [event["type"] for event in decoded] == ["start", "delta", "done"]
