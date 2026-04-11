"""
OrchestratorAgent: central dispatcher that replaces hardcoded if-else routing.

Receives requests, classifies intent via IntentRouter, resolves the
target pipeline through SkillRegistry, and executes it.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.agents.base import RawResult, Rejection, ValidatedOutput
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
    """Central dispatcher: classify intent -> resolve pipeline -> execute.

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

    def _resolve_pipeline(self, intent: str) -> AgentPipeline:
        """Resolve intent to a pipeline instance."""
        try:
            entry = self._registry.discover(intent)
        except KeyError:
            logger.warning("Intent '%s' not found in registry, falling back to chat", intent)
            try:
                entry = self._registry.discover("chat")
            except KeyError:
                raise KeyError(f"intent '{intent}' not found and no chat fallback") from None

        factory = entry.agent_class
        if hasattr(factory, "create"):
            return factory.create()
        return factory()  # type: ignore[operator]

    async def dispatch(
        self,
        *,
        endpoint: str,
        payload: dict[str, Any],
    ) -> RawResult | ValidatedOutput | Rejection:
        """Dispatch a request to the appropriate agent pipeline.

        Args:
            endpoint: API endpoint path (e.g., "/api/chat/stream")
            payload: Request payload

        Returns:
            Result from the executed pipeline
        """
        intent = self._router.classify(endpoint, payload)

        try:
            pipeline = self._resolve_pipeline(intent)
        except KeyError as exc:
            return RawResult(status="error", output=None, error=str(exc))

        return await pipeline.run(payload)

    async def dispatch_stream(
        self,
        *,
        endpoint: str,
        payload: dict[str, Any],
        stream_fn_name: str = "stream",
    ) -> AsyncIterator[str]:
        """Dispatch a streaming request to the appropriate agent pipeline.

        Looks up the streaming function (e.g., stream_chat_pipeline,
        stream_contract_review_pipeline) based on intent and yields events.
        """
        intent = self._router.classify(endpoint, payload)

        # Map intent to its streaming function
        _STREAM_FN_MAP: dict[str, tuple[str, str]] = {
            "chat": ("app.agents.chat", "stream_chat_pipeline"),
            "contract_review": ("app.agents.contract_review", "stream_contract_review_pipeline"),
        }

        if intent in _STREAM_FN_MAP:
            module_path, fn_name = _STREAM_FN_MAP[intent]
            import importlib
            module = importlib.import_module(module_path)
            stream_fn = getattr(module, fn_name)
            async for event in stream_fn(payload):
                yield event
            return

        # Fallback: non-streaming intent, wrap as single event
        result = await self.dispatch(endpoint=endpoint, payload=payload)
        import json
        if isinstance(result, RawResult):
            yield json.dumps({"type": "done", "output": result.output}) + "\n"
        elif isinstance(result, ValidatedOutput):
            yield json.dumps({"type": "done", "output": result.output}) + "\n"
        else:
            yield json.dumps({"type": "error", "detail": str(result)}) + "\n"

