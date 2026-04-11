"""
Orchestrator integration: wires SkillRegistry with pipeline factories.

Provides get_orchestrator() singleton that the route layer uses
instead of direct pipeline imports.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.orchestrator import IntentRouter, OrchestratorAgent
from app.agents.pipeline import AgentPipeline
from app.agents.registry import SkillRegistry

logger = logging.getLogger(__name__)

_orchestrator: OrchestratorAgent | None = None


class PipelineFactory:
    """Generic pipeline factory that delegates to a create function."""

    def __init__(self, create_fn: Any) -> None:
        self._create_fn = create_fn

    def create(self, **kwargs: Any) -> AgentPipeline:
        return self._create_fn(**kwargs)


def _build_registry() -> SkillRegistry:
    """Build and populate the SkillRegistry with all pipeline factories."""
    registry = SkillRegistry()

    def _create_chat_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.chat import create_chat_pipeline
        return create_chat_pipeline(**kw)

    def _create_similar_case_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.similar_case import create_similar_case_pipeline
        return create_similar_case_pipeline(**kw)

    def _create_contract_review_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.contract_review import create_contract_review_pipeline
        return create_contract_review_pipeline(**kw)

    def _create_opponent_prediction_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.opponent_prediction import create_opponent_prediction_pipeline
        return create_opponent_prediction_pipeline(**kw)

    registry.register(
        "chat",
        PipelineFactory(_create_chat_pipeline),
        {"description": "Grounded chat pipeline"},
    )
    registry.register(
        "similar_case_search",
        PipelineFactory(_create_similar_case_pipeline),
        {"description": "Similar case search pipeline"},
    )
    registry.register(
        "contract_review",
        PipelineFactory(_create_contract_review_pipeline),
        {"description": "Contract review pipeline"},
    )
    registry.register(
        "opponent_prediction",
        PipelineFactory(_create_opponent_prediction_pipeline),
        {"description": "Opponent prediction pipeline"},
    )

    return registry


def get_orchestrator() -> OrchestratorAgent:
    """Get or create the singleton OrchestratorAgent."""
    global _orchestrator
    if _orchestrator is None:
        registry = _build_registry()
        _orchestrator = OrchestratorAgent(registry=registry)
        logger.info("OrchestratorAgent initialized with %d capabilities", len(registry.list_capabilities()))
    return _orchestrator
