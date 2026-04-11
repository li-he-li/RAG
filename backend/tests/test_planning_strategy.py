"""Tests for PlanningStrategy and dynamic plan generation."""
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import (
    ExecutionPlan,
    ExecutorAgent,
    PlanStep,
    PlannerAgent,
    RawResult,
)
from app.agents.pipeline import AgentPipeline
from app.agents.strategies import (
    PlanningStrategy,
    StrategyRegistry,
    InputComplexity,
    classify_complexity,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- Input complexity classification ---


def test_classify_simple_query() -> None:
    result = classify_complexity({"query": "你好", "attachments": []})
    assert result == InputComplexity.SIMPLE


def test_classify_medium_query() -> None:
    result = classify_complexity({
        "query": "合同第三条有什么风险",
        "attachments": [{"name": "contract.pdf"}],
    })
    assert result == InputComplexity.MEDIUM


def test_classify_complex_query() -> None:
    result = classify_complexity({
        "query": "请详细分析这份合同的所有风险条款并找到类似案例",
        "attachments": [
            {"name": "contract1.pdf"},
            {"name": "contract2.pdf"},
            {"name": "evidence.pdf"},
        ],
        "dispute_tags": ["违约责任", "赔偿金额", "管辖权"],
    })
    assert result == InputComplexity.COMPLEX


# --- StrategyRegistry ---


def test_strategy_registry_register_and_select() -> None:
    registry = StrategyRegistry()

    class DummyStrategy(PlanningStrategy):
        @property
        def name(self) -> str:
            return "dummy"

        def should_apply(self, complexity: InputComplexity) -> bool:
            return complexity == InputComplexity.SIMPLE

        async def build_plan(self, input_data: dict[str, Any]) -> ExecutionPlan:
            return ExecutionPlan(steps=(
                PlanStep(name="single", target_agent="executor"),
            ))

    registry.register(DummyStrategy())
    strategy = registry.select(InputComplexity.SIMPLE)
    assert strategy is not None
    assert strategy.name == "dummy"


def test_strategy_registry_returns_none_for_no_match() -> None:
    registry = StrategyRegistry()
    assert registry.select(InputComplexity.COMPLEX) is None


# --- Dynamic planning with strategy ---


class StrategyDrivenPlanner(PlannerAgent):
    """Planner that uses StrategyRegistry to select plan structure."""

    def __init__(self, strategy_registry: StrategyRegistry) -> None:
        self._registry = strategy_registry

    @property
    def name(self) -> str:
        return "strategy_planner"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> ExecutionPlan:
        complexity = classify_complexity(input_data)
        strategy = self._registry.select(complexity)
        if strategy is not None:
            return await strategy.build_plan(input_data)
        # Fallback: single step
        return ExecutionPlan(steps=(
            PlanStep(name="default", target_agent="executor"),
        ))


class SimpleStrategy(PlanningStrategy):
    @property
    def name(self) -> str:
        return "simple"

    def should_apply(self, complexity: InputComplexity) -> bool:
        return complexity == InputComplexity.SIMPLE

    async def build_plan(self, input_data: dict[str, Any]) -> ExecutionPlan:
        return ExecutionPlan(steps=(
            PlanStep(name="single_step", target_agent="executor"),
        ))


class ComplexStrategy(PlanningStrategy):
    @property
    def name(self) -> str:
        return "complex"

    def should_apply(self, complexity: InputComplexity) -> bool:
        return complexity in (InputComplexity.MEDIUM, InputComplexity.COMPLEX)

    async def build_plan(self, input_data: dict[str, Any]) -> ExecutionPlan:
        steps = [
            PlanStep(name="analyze_input", target_agent="executor"),
            PlanStep(name="retrieve_evidence", target_agent="executor"),
        ]
        if classify_complexity(input_data) == InputComplexity.COMPLEX:
            steps.append(
                PlanStep(name="cross_reference", target_agent="executor",
                         condition="dispute_tags != None"),
            )
        return ExecutionPlan(steps=tuple(steps))


class RecordingExecutor(ExecutorAgent):
    def __init__(self) -> None:
        self.plans_received: list[ExecutionPlan] = []

    @property
    def name(self) -> str:
        return "executor"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: Any) -> RawResult:
        if isinstance(input_data, ExecutionPlan):
            self.plans_received.append(input_data)
            return RawResult(
                status="success",
                output={"steps": [s.name for s in input_data.steps]},
            )
        return RawResult(status="success", output={"data": str(input_data)})


def test_simple_input_gets_single_step_plan() -> None:
    registry = StrategyRegistry()
    registry.register(SimpleStrategy())
    registry.register(ComplexStrategy())

    executor = RecordingExecutor()
    planner = StrategyDrivenPlanner(registry)
    pipeline = AgentPipeline(planner=planner, executor=executor)

    result = _run(pipeline.run({"query": "你好", "attachments": []}))
    assert isinstance(result, RawResult)
    assert len(result.output["steps"]) == 1
    assert result.output["steps"][0] == "single_step"


def test_complex_input_gets_multi_step_plan() -> None:
    registry = StrategyRegistry()
    registry.register(SimpleStrategy())
    registry.register(ComplexStrategy())

    executor = RecordingExecutor()
    planner = StrategyDrivenPlanner(registry)
    pipeline = AgentPipeline(planner=planner, executor=executor)

    result = _run(pipeline.run({
        "query": "详细分析合同风险",
        "attachments": [{"name": "a.pdf"}, {"name": "b.pdf"}, {"name": "c.pdf"}],
        "dispute_tags": ["违约", "赔偿"],
    }))
    assert isinstance(result, RawResult)
    # complex strategy: analyze_input + retrieve_evidence + cross_reference (condition met)
    assert len(result.output["steps"]) == 3
    assert "cross_reference" in result.output["steps"]


def test_medium_input_gets_two_steps_without_cross_reference() -> None:
    registry = StrategyRegistry()
    registry.register(SimpleStrategy())
    registry.register(ComplexStrategy())

    executor = RecordingExecutor()
    planner = StrategyDrivenPlanner(registry)
    pipeline = AgentPipeline(planner=planner, executor=executor)

    result = _run(pipeline.run({
        "query": "合同第三条风险",
        "attachments": [{"name": "contract.pdf"}],
    }))
    assert isinstance(result, RawResult)
    assert len(result.output["steps"]) == 2
    assert "cross_reference" not in result.output["steps"]


def test_fallback_when_no_strategy_matches() -> None:
    registry = StrategyRegistry()  # empty

    executor = RecordingExecutor()
    planner = StrategyDrivenPlanner(registry)
    pipeline = AgentPipeline(planner=planner, executor=executor)

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, RawResult)
    assert len(result.output["steps"]) == 1
    assert result.output["steps"][0] == "default"
