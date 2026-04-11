"""
OrchestratorAgent: central dispatcher that replaces hardcoded if-else routing.

Receives requests, classifies intent via IntentRouter, resolves the
target pipeline through SkillRegistry, and executes it.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import RawResult
from app.agents.pipeline import AgentPipeline
from app.agents.registry import SkillRegistry

logger = logging.getLogger(__name__)


class IntentRouter:
    """Deterministic intent classification based on endpoint path + payload."""

    # Maps (path_prefix, payload_key) -> intent name
    _RULES: list[tuple[str, str | None, str]] = [
        ("/api/chat", None, "chat"),
        ("/api/search", None, "chat"),
        ("/api/similar-cases", None, "similar_case_search"),
        ("/api/contract-review", None, "contract_review"),
        ("/api/opponent-prediction", None, "opponent_prediction"),
        ("/api/prediction", None, "opponent_prediction"),
    ]

    _DEFAULT_INTENT = "chat"

    def classify(self, endpoint: str, payload: dict[str, Any]) -> str:
        """Classify intent from endpoint path and payload structure.

        Returns the intent name, defaulting to 'chat' for unknown paths.
        """
        if not endpoint:
            return self._DEFAULT_INTENT

        for path_prefix, payload_key, intent in self._RULES:
            if endpoint.startswith(path_prefix):
                return intent

        return self._DEFAULT_INTENT


class OrchestratorAgent:
    """Central dispatcher: classify intent → resolve pipeline → execute.

    This agent does NOT contain business logic. It only:
    1. Classifies intent via IntentRouter
    2. Resolves pipeline via SkillRegistry
    3. Executes the pipeline
    4. Returns the result
    """

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        intent_router: IntentRouter | None = None,
    ) -> None:
        self._registry = registry
        self._router = intent_router or IntentRouter()

    async def dispatch(
        self,
        *,
        endpoint: str,
        payload: dict[str, Any],
    ) -> RawResult:
        """Dispatch a request to the appropriate agent pipeline.

        Args:
            endpoint: API endpoint path (e.g., "/api/chat/stream")
            payload: Request payload

        Returns:
            RawResult from the executed pipeline
        """
        intent = self._router.classify(endpoint, payload)

        try:
            entry = self._registry.discover(intent)
        except KeyError:
            logger.warning("Intent '%s' not found in registry, falling back to chat", intent)
            try:
                entry = self._registry.discover("chat")
            except KeyError:
                return RawResult(
                    status="error",
                    output=None,
                    error=f"intent '{intent}' not found and no chat fallback",
                )

        # The registry stores the pipeline factory class
        factory = entry.agent_class
        if hasattr(factory, "create"):
            pipeline: AgentPipeline = factory.create()
        else:
            # If it's already an AgentPipeline class, instantiate it
            pipeline = factory()  # type: ignore[operator]

        return await pipeline.run(payload)
