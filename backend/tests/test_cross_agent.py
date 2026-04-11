"""Tests for cross-agent collaboration via AgentTool."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from app.agents.base import (
    AgentBase,
    ExecutorAgent,
    RawResult,
    ValidatedOutput,
    ValidatorAgent,
)
from app.agents.agent_tool import AgentTool
from app.agents.tool_governance import (
    ToolGovernancePolicy,
    ToolRegistry,
    ToolSideEffectLevel,
)
from app.agents.pipeline import AgentPipeline


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- Mock agents for cross-agent calls ---


class SimilarCaseAgent(ExecutorAgent):
    """Returns mock similar cases."""

    @property
    def name(self) -> str:
        return "similar_case_agent"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        return RawResult(
            status="success",
            output={
                "similar_cases": [
                    {"case_name": "Case A", "similarity": 0.85},
                    {"case_name": "Case B", "similarity": 0.72},
                ],
            },
        )

    async def can_handle(self, input_data: Any) -> float:
        if isinstance(input_data, dict) and "query" in input_data:
            return 0.9
        return 0.0


class RetrievalAgent(ExecutorAgent):
    """Returns mock retrieval evidence."""

    @property
    def name(self) -> str:
        return "retrieval_agent"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        return RawResult(
            status="success",
            output={
                "evidence": [
                    {"doc": "Contract Law Art.94", "score": 0.9},
                ],
            },
        )


class ContractReviewAgent(ExecutorAgent):
    """Contract review that can optionally call similar_case_agent."""

    @property
    def name(self) -> str:
        return "contract_review_agent"

    def __init__(self, *, governance: ToolGovernancePolicy | None = None) -> None:
        super().__init__(tool_governance_policy=governance)

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        findings = [{"clause": "Clause 3", "risk": "high"}]

        # Cross-agent call: if dispute_tags present, call similar_case
        cross_refs = []
        if input_data.get("dispute_tags"):
            similar = await self.invoke_tool(
                "similar_case_search",
                {"query": input_data.get("query", ""), "_recursion_depth": 1},
            )
            if similar:
                cross_refs = similar.get("similar_cases", [])

        return RawResult(
            status="success",
            output={
                "findings": findings,
                "cross_references": cross_refs,
            },
        )

    async def can_handle(self, input_data: Any) -> float:
        if isinstance(input_data, dict) and "query" in input_data:
            return 0.8
        return 0.0


class SimpleInput(BaseModel):
    query: str
    _recursion_depth: int = 0

    class Config:
        extra = "allow"


# --- Cross-agent collaboration tests ---


def _setup_governance() -> ToolGovernancePolicy:
    registry = ToolRegistry()
    similar_agent = SimilarCaseAgent()
    similar_tool = AgentTool(similar_agent)
    registry.register(
        name="similar_case_search",
        func=similar_tool,
        args_schema=SimpleInput,
        side_effect_level=ToolSideEffectLevel.READ_ONLY,
    )
    return ToolGovernancePolicy(registry=registry, max_recursion_depth=3)


def test_contract_review_without_cross_ref() -> None:
    """Simple review without dispute_tags does not call similar_case."""
    governance = _setup_governance()
    agent = ContractReviewAgent(governance=governance)
    result = _run(agent.run({"query": "review this contract"}))
    assert result.status == "success"
    assert len(result.output["findings"]) == 1
    assert result.output["cross_references"] == []


def test_contract_review_with_cross_ref() -> None:
    """Review WITH dispute_tags triggers cross-agent call to similar_case."""
    governance = _setup_governance()
    agent = ContractReviewAgent(governance=governance)
    result = _run(agent.run({
        "query": "analyze breach clauses",
        "dispute_tags": ["breach", "compensation"],
    }))
    assert result.status == "success"
    assert len(result.output["cross_references"]) == 2
    assert result.output["cross_references"][0]["case_name"] == "Case A"


def test_cross_agent_result_included_in_output() -> None:
    """Cross-agent results are properly merged into the calling agent's output."""
    governance = _setup_governance()
    agent = ContractReviewAgent(governance=governance)
    result = _run(agent.run({
        "query": "detailed analysis",
        "dispute_tags": ["liability"],
    }))
    assert result.output["findings"][0]["clause"] == "Clause 3"
    assert any("Case" in ref["case_name"] for ref in result.output["cross_references"])


def test_cross_agent_via_pipeline() -> None:
    """Full pipeline execution with cross-agent call."""
    governance = _setup_governance()
    executor = ContractReviewAgent(governance=governance)
    pipeline = AgentPipeline(executor=executor)

    result = _run(pipeline.run({
        "query": "contract risks",
        "dispute_tags": ["termination"],
    }))
    assert isinstance(result, RawResult)
    assert result.output["cross_references"]
