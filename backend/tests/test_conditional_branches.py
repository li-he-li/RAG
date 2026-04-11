"""Tests for ExecutionPlan conditional branches and PlanStep.condition."""
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import (
    ExecutionPlan,
    ExecutorAgent,
    PlanStep,
    PlannerAgent,
    RawResult,
    Rejection,
    ValidatedOutput,
    ValidatorAgent,
)
from app.agents.pipeline import AgentPipeline


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- PlanStep condition field ---


def test_plan_step_has_condition_field() -> None:
    step = PlanStep(
        name="test",
        target_agent="executor",
        condition="has_attachments == True",
    )
    assert step.condition == "has_attachments == True"
    assert step.parallel_group is None


def test_plan_step_has_parallel_group_field() -> None:
    step = PlanStep(
        name="test",
        target_agent="executor",
        parallel_group="search_ops",
    )
    assert step.parallel_group == "search_ops"
    assert step.condition is None


def test_plan_step_defaults_to_no_condition() -> None:
    step = PlanStep(name="test", target_agent="executor")
    assert step.condition is None
    assert step.parallel_group is None


# --- Pipeline conditional execution ---


class ConditionalPlanner(PlannerAgent):
    """Planner that produces steps with conditions."""

    @property
    def name(self) -> str:
        return "conditional_planner"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> ExecutionPlan:
        return ExecutionPlan(
            steps=(
                PlanStep(
                    name="always_step",
                    target_agent="cond_executor",
                    input_mapping={"value": input_data.get("value", "")},
                ),
                PlanStep(
                    name="conditional_step",
                    target_agent="cond_executor",
                    condition="has_extra == True",
                    input_mapping={"value": "extra"},
                ),
                PlanStep(
                    name="skip_me",
                    target_agent="cond_executor",
                    condition="never_true == True",
                    input_mapping={"value": "should_not_appear"},
                ),
            )
        )


class ConditionalExecutor(ExecutorAgent):
    """Executor that records which steps actually ran."""

    def __init__(self) -> None:
        self.executed_steps: list[str] = []

    @property
    def name(self) -> str:
        return "cond_executor"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: Any) -> RawResult:
        if isinstance(input_data, ExecutionPlan):
            for step in input_data.steps:
                self.executed_steps.append(step.name)
            return RawResult(
                status="success",
                output={"executed": [s.name for s in input_data.steps]},
            )
        return RawResult(status="success", output={"value": str(input_data)})


def test_conditional_pipeline_executes_unconditional_steps() -> None:
    """Steps without conditions always execute."""
    executor = ConditionalExecutor()
    pipeline = AgentPipeline(planner=ConditionalPlanner(), executor=executor)

    result = _run(pipeline.run({"value": "test"}))
    assert isinstance(result, RawResult)
    assert "always_step" in result.output["executed"]


def test_conditional_step_with_true_condition_executes() -> None:
    """Steps with condition evaluating to True execute."""
    executor = ConditionalExecutor()
    pipeline = AgentPipeline(planner=ConditionalPlanner(), executor=executor)

    context = {"value": "test", "has_extra": True}
    result = _run(pipeline.run(context))
    assert isinstance(result, RawResult)
    assert "conditional_step" in result.output["executed"]


def test_conditional_step_with_false_condition_skipped() -> None:
    """Steps with condition evaluating to False are skipped."""
    executor = ConditionalExecutor()
    pipeline = AgentPipeline(planner=ConditionalPlanner(), executor=executor)

    context = {"value": "test"}  # has_extra not set -> False
    result = _run(pipeline.run(context))
    assert isinstance(result, RawResult)
    assert "conditional_step" not in result.output["executed"]
    assert "skip_me" not in result.output["executed"]


def test_never_true_condition_always_skipped() -> None:
    """A condition that's never true means the step is always skipped."""
    executor = ConditionalExecutor()
    pipeline = AgentPipeline(planner=ConditionalPlanner(), executor=executor)

    result = _run(pipeline.run({"value": "anything"}))
    assert isinstance(result, RawResult)
    assert "skip_me" not in result.output["executed"]
