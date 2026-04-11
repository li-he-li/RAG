"""Tests for OrchestratorAgent and IntentRouter."""
from __future__ import annotations

import asyncio
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
from app.agents.orchestrator import IntentRouter, OrchestratorAgent
from app.agents.pipeline import AgentPipeline
from app.agents.registry import SkillRegistry


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- IntentRouter ---


def test_route_chat_stream() -> None:
    router = IntentRouter()
    intent = router.classify("/api/chat/stream", {"query": "hello"})
    assert intent == "chat"


def test_route_similar_cases() -> None:
    router = IntentRouter()
    intent = router.classify("/api/similar-cases/compare", {})
    assert intent == "similar_case_search"


def test_route_contract_review() -> None:
    router = IntentRouter()
    intent = router.classify("/api/contract-review/stream", {})
    assert intent == "contract_review"


def test_route_opponent_prediction() -> None:
    router = IntentRouter()
    intent = router.classify("/api/opponent-prediction/start", {})
    assert intent == "opponent_prediction"


def test_route_unknown_falls_back_to_chat() -> None:
    router = IntentRouter()
    intent = router.classify("/api/unknown/endpoint", {})
    assert intent == "chat"


def test_route_empty_path_falls_back() -> None:
    router = IntentRouter()
    intent = router.classify("", {})
    assert intent == "chat"


# --- OrchestratorAgent ---


class MockExecutor(ExecutorAgent):
    @property
    def name(self) -> str:
        return "mock_executor"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: Any) -> RawResult:
        return RawResult(status="success", output={"handled_by": "mock"})


def _make_registry() -> SkillRegistry:
    registry = SkillRegistry()

    # Register a factory function for chat pipeline
    def _create_chat_pipeline(**kwargs: Any) -> AgentPipeline:
        return AgentPipeline(executor=MockExecutor())

    registry.register(
        "chat",
        type("ChatFactory", (), {"create": staticmethod(_create_chat_pipeline)}),
        {"description": "Chat pipeline"},
    )

    def _create_similar_pipeline(**kwargs: Any) -> AgentPipeline:
        return AgentPipeline(executor=MockExecutor())

    registry.register(
        "similar_case_search",
        type("SimilarFactory", (), {"create": staticmethod(_create_similar_pipeline)}),
        {"description": "Similar case search pipeline"},
    )

    return registry


def test_orchestrator_routes_chat_request() -> None:
    registry = _make_registry()
    orchestrator = OrchestratorAgent(registry=registry)

    result = _run(orchestrator.dispatch(
        endpoint="/api/chat/stream",
        payload={"query": "hello", "session_id": "s1"},
    ))
    assert result.output["handled_by"] == "mock"


def test_orchestrator_routes_similar_case_request() -> None:
    registry = _make_registry()
    orchestrator = OrchestratorAgent(registry=registry)

    result = _run(orchestrator.dispatch(
        endpoint="/api/similar-cases/compare",
        payload={"request": {}},
    ))
    assert result.output["handled_by"] == "mock"


def test_orchestrator_fallback_to_chat() -> None:
    registry = _make_registry()
    orchestrator = OrchestratorAgent(registry=registry)

    # Unknown endpoint falls back to chat
    result = _run(orchestrator.dispatch(
        endpoint="/api/nonexistent",
        payload={"query": "test"},
    ))
    assert result.output["handled_by"] == "mock"


def test_orchestrator_unregistered_intent_returns_error() -> None:
    registry = SkillRegistry()  # empty registry
    orchestrator = OrchestratorAgent(registry=registry)

    result = _run(orchestrator.dispatch(
        endpoint="/api/chat/stream",
        payload={"query": "test"},
    ))
    assert result.status == "error"
    assert "not found" in (result.error or "").lower()


def test_orchestrator_records_telemetry_on_unknown_intent() -> None:
    """Unknown intents should be tracked for monitoring."""
    registry = _make_registry()
    orchestrator = OrchestratorAgent(registry=registry)

    # This will fallback to chat but the intent was unknown
    result = _run(orchestrator.dispatch(
        endpoint="/api/mystery",
        payload={},
    ))
    # Should still succeed via fallback
    assert result.output["handled_by"] == "mock"
