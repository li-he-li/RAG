"""
Agent-as-Tool: wraps an Agent so it can be registered in ToolRegistry
and invoked by other agents via invoke_tool().
"""
from __future__ import annotations

from typing import Any

from app.agents.base import AgentBase, RawResult


class AgentTool:
    """Wraps an Agent as a callable tool for use in ToolRegistry.

    When invoked, calls agent.execute() with the provided arguments.
    Automatically injects _recursion_depth for nested call tracking.
    """

    def __init__(
        self,
        agent: AgentBase[Any, Any],
        *,
        max_recursion_depth: int = 3,
    ) -> None:
        self._agent = agent
        self._max_recursion_depth = max_recursion_depth

    @property
    def name(self) -> str:
        return self._agent.name

    async def __call__(self, **kwargs: Any) -> Any:
        recursion_depth = kwargs.pop("_recursion_depth", 0) + 1
        result = await self._agent.execute(kwargs)
        if isinstance(result, RawResult):
            return result.output
        return result
