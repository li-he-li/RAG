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
from app.routers.trajectory import get_trajectory_store

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
    from app.services.trajectory.logger import TrajectoryLogger

    registry = SkillRegistry()
    store = get_trajectory_store()

    def _make_logger(session_id: str) -> TrajectoryLogger:
        return TrajectoryLogger(session_id=session_id, trajectory_store=store)

    def _create_chat_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.chat import create_chat_pipeline
        session_id = kw.get("session_id", "default")
        kw.setdefault("trajectory_logger", _make_logger(session_id))
        return create_chat_pipeline(**kw)

    def _create_similar_case_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.similar_case import create_similar_case_pipeline
        session_id = kw.get("session_id", "default")
        kw.setdefault("trajectory_logger", _make_logger(session_id))
        return create_similar_case_pipeline(**kw)

    def _create_contract_review_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.contract_review import create_contract_review_pipeline
        session_id = kw.get("session_id", "default")
        kw.setdefault("trajectory_logger", _make_logger(session_id))
        return create_contract_review_pipeline(**kw)

    def _create_opponent_prediction_pipeline(**kw: Any) -> AgentPipeline:
        from app.agents.opponent_prediction import create_opponent_prediction_pipeline
        session_id = kw.get("session_id", "default")
        kw.setdefault("trajectory_logger", _make_logger(session_id))
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


def register_agents_as_tools(governance: Any = None) -> None:
    """Register all business agents as tools in the ToolRegistry."""
    from app.agents.agent_tool import AgentTool
    from app.agents.tool_governance import ToolGovernancePolicy, ToolRegistry, ToolSideEffectLevel
    from pydantic import BaseModel

    class ToolInput(BaseModel):
        class Config:
            extra = "allow"

    policy = governance or ToolGovernancePolicy()
    registry = policy.registry

    agents_to_register = [
        ("similar_case_search", "app.agents.similar_case", "SimilarCaseExecutor"),
        ("grounded_chat", "app.agents.chat", "ChatExecutor"),
        ("contract_review", "app.agents.contract_review", "ContractReviewExecutor"),
        ("opponent_prediction", "app.agents.opponent_prediction", "PredictionExecutor"),
    ]

    for tool_name, module_path, class_name in agents_to_register:
        try:
            import importlib
            module = importlib.import_module(module_path)
            agent_class = getattr(module, class_name)
            agent_instance = agent_class()
            tool = AgentTool(agent_instance)
            registry.register(
                name=tool_name,
                func=tool,
                args_schema=ToolInput,
                side_effect_level=ToolSideEffectLevel.READ_ONLY,
            )
            logger.info("Registered agent tool: %s", tool_name)
        except Exception as exc:
            logger.warning("Failed to register agent tool %s: %s", tool_name, exc)


def get_orchestrator() -> OrchestratorAgent:
    """Get or create the singleton OrchestratorAgent."""
    global _orchestrator
    if _orchestrator is None:
        registry = _build_registry()
        _orchestrator = OrchestratorAgent(registry=registry)
        logger.info("OrchestratorAgent initialized with %d capabilities", len(registry.list_capabilities()))
    return _orchestrator
