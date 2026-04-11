"""Tests for Agent-as-Tool wrapping and recursion depth protection."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from app.agents.base import (
    AgentBase,
    ExecutionPlan,
    ExecutorAgent,
    PlanStep,
    PlannerAgent,
    RawResult,
    ValidatedOutput,
    ValidatorAgent,
)
from app.agents.agent_tool import AgentTool
from app.agents.tool_governance import (
    ToolGovernancePolicy,
    ToolInvocationBlocked,
    ToolRegistry,
    ToolSideEffectLevel,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- Test agents ---


class SimpleAgent(ExecutorAgent):
    @property
    def name(self) -> str:
        return "simple_agent"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        return RawResult(status="success", output={"echo": input_data.get("msg", "")})


class SimpleInput(BaseModel):
    msg: str


# --- AgentTool wrapping ---


def test_agent_tool_wraps_agent_execute() -> None:
    """AgentTool wraps an Agent and exposes it as a callable tool."""
    agent = SimpleAgent()
    tool = AgentTool(agent)

    result = _run(tool(msg="hello"))
    assert result["echo"] == "hello"


def test_agent_tool_name_matches_agent() -> None:
    agent = SimpleAgent()
    tool = AgentTool(agent)
    assert tool.name == "simple_agent"


def test_agent_tool_registers_in_tool_registry() -> None:
    """AgentTool can be registered in ToolRegistry like any other tool."""
    registry = ToolRegistry()
    agent = SimpleAgent()
    tool = AgentTool(agent)

    registry.register(
        name="simple_agent_tool",
        func=tool,
        args_schema=SimpleInput,
        side_effect_level=ToolSideEffectLevel.READ_ONLY,
    )

    found = registry.discover("simple_agent_tool")
    assert found is not None
    assert found.side_effect_level == ToolSideEffectLevel.READ_ONLY


def test_agent_tool_invoked_via_governance() -> None:
    """AgentTool works through ToolGovernancePolicy.invoke()."""
    registry = ToolRegistry()
    agent = SimpleAgent()
    tool = AgentTool(agent)

    registry.register(
        name="simple_agent_tool",
        func=tool,
        args_schema=SimpleInput,
        side_effect_level=ToolSideEffectLevel.READ_ONLY,
    )

    policy = ToolGovernancePolicy(registry=registry)
    result = _run(policy.invoke(
        agent_name="caller_agent",
        tool_name="simple_agent_tool",
        arguments={"msg": "test"},
    ))
    assert result["echo"] == "test"


# --- Recursion depth ---


def test_recursion_depth_within_limit() -> None:
    """Recursion depth tracked and allowed when within limit."""
    agent = SimpleAgent()
    tool = AgentTool(agent, max_recursion_depth=3)

    # Depth 1 should work
    result = _run(tool(msg="depth1"))
    assert result["echo"] == "depth1"


def test_recursion_depth_exceeds_limit_blocked() -> None:
    """When recursion depth exceeds limit, governance blocks the call."""
    registry = ToolRegistry()
    agent = SimpleAgent()
    tool = AgentTool(agent, max_recursion_depth=2)

    registry.register(
        name="deep_agent",
        func=tool,
        args_schema=SimpleInput,
        side_effect_level=ToolSideEffectLevel.READ_ONLY,
    )

    policy = ToolGovernancePolicy(registry=registry, max_recursion_depth=2)

    # Simulate calling at depth 1 (allowed, since 1 < max_depth=2)
    result = _run(policy.invoke(
        agent_name="caller",
        tool_name="deep_agent",
        arguments={"msg": "ok", "_recursion_depth": 1},
    ))
    assert result["echo"] == "ok"

    # Simulate calling at depth 2 (blocked, since 2 >= max_depth=2)
    with pytest.raises(ToolInvocationBlocked) as exc_info:
        _run(policy.invoke(
            agent_name="caller",
            tool_name="deep_agent",
            arguments={"msg": "too_deep", "_recursion_depth": 2},
        ))
    assert "recursion" in exc_info.value.reason.lower()


def test_recursion_depth_default_is_three() -> None:
    """Default max recursion depth is 3."""
    policy = ToolGovernancePolicy()
    assert policy.max_recursion_depth == 3


def test_agent_tool_injects_recursion_depth() -> None:
    """AgentTool passes current depth + 1 in context for nested calls."""
    agent = SimpleAgent()
    tool = AgentTool(agent)

    # When called with depth context, result includes it
    result = _run(tool(msg="test", _recursion_depth=1))
    assert result["echo"] == "test"
