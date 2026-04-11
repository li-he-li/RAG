"""Tests for Orchestrator integration with pipeline factories."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import RawResult, ValidatedOutput
from app.agents.orchestrator_integration import PipelineFactory, get_orchestrator


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_pipeline_factory_delegates_to_create_fn() -> None:
    mock_pipeline = MagicMock()
    create_fn = MagicMock(return_value=mock_pipeline)

    factory = PipelineFactory(create_fn)
    result = factory.create()

    create_fn.assert_called_once()
    assert result is mock_pipeline


def test_get_orchestrator_returns_singleton() -> None:
    # Reset singleton
    import app.agents.orchestrator_integration as mod
    mod._orchestrator = None

    orch1 = get_orchestrator()
    orch2 = get_orchestrator()
    assert orch1 is orch2

    # Cleanup
    mod._orchestrator = None


def test_orchestrator_routes_to_chat_pipeline() -> None:
    """Orchestrator dispatches chat intent to chat pipeline factory."""
    import app.agents.orchestrator_integration as mod
    mod._orchestrator = None

    orch = get_orchestrator()
    # Verify chat is registered
    entry = orch._registry.discover("chat")
    assert entry is not None
    assert entry.metadata["description"] == "Grounded chat pipeline"

    mod._orchestrator = None


def test_all_four_intents_registered() -> None:
    """All 4 business intents are registered in the SkillRegistry."""
    import app.agents.orchestrator_integration as mod
    mod._orchestrator = None

    orch = get_orchestrator()
    caps = orch._registry.list_capabilities()
    names = {c["name"] for c in caps}
    assert names == {"chat", "similar_case_search", "contract_review", "opponent_prediction"}

    mod._orchestrator = None


def test_intent_router_maps_all_endpoints() -> None:
    """IntentRouter correctly maps all 4 API endpoint prefixes."""
    from app.agents.orchestrator import IntentRouter

    router = IntentRouter()
    assert router.classify("/api/chat/stream", {}) == "chat"
    assert router.classify("/api/chat", {}) == "chat"
    assert router.classify("/api/similar-cases/compare", {}) == "similar_case_search"
    assert router.classify("/api/contract-review/stream", {}) == "contract_review"
    assert router.classify("/api/opponent-prediction/start", {}) == "opponent_prediction"
    assert router.classify("/api/prediction/templates", {}) == "opponent_prediction"
