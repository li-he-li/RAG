"""Tests for AgentPipeline self-correction loop."""
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


# --- Self-correction with retryable failures ---


class RetryCountingExecutor(ExecutorAgent):
    """Fails first N times, then succeeds."""

    def __init__(self, fail_count: int = 1) -> None:
        self.attempts = 0
        self._fail_count = fail_count

    @property
    def name(self) -> str:
        return "retry_executor"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: Any) -> RawResult:
        self.attempts += 1
        if self.attempts <= self._fail_count:
            return RawResult(status="success", output={"short": True})
        return RawResult(status="success", output={"answer": "full response", "citations": []})


class RePlanningPlanner(PlannerAgent):
    """Planner that tracks how many times it's called (for retry tracking)."""

    def __init__(self) -> None:
        self.plan_count = 0

    @property
    def name(self) -> str:
        return "replan_planner"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: Any) -> ExecutionPlan:
        self.plan_count += 1
        # If input contains rejection feedback, adjust plan
        if isinstance(input_data, dict) and "rejection_feedback" in input_data:
            return ExecutionPlan(steps=(
                PlanStep(name="adjusted_step", target_agent="retry_executor"),
            ))
        return ExecutionPlan(steps=(
            PlanStep(name="initial_step", target_agent="retry_executor"),
        ))


class StrictValidator(ValidatorAgent):
    """Validator that rejects output without 'citations' key, retryable."""

    @property
    def name(self) -> str:
        return "strict_validator"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, raw_result: RawResult) -> ValidatedOutput | Rejection:
        if raw_result.status == "error":
            return ValidatedOutput(
                output=raw_result.output,
                schema_name="RawResult",
                metadata={"error": raw_result.error},
            )
        output = raw_result.output or {}
        if isinstance(output, dict) and "citations" not in output:
            return Rejection(
                reasons=("missing_citations", "output_incomplete"),
                details={"retryable": True},
            )
        return ValidatedOutput(output=output, schema_name="Validated")


class PermissionDeniedValidator(ValidatorAgent):
    """Validator that rejects with non-retryable reason."""

    @property
    def name(self) -> str:
        return "permission_validator"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, raw_result: RawResult) -> ValidatedOutput | Rejection:
        return Rejection(
            reasons=("permission_denied",),
            details={"retryable": False},
        )


def test_self_correction_succeeds_after_retry() -> None:
    """Executor fails once, planner re-plans, executor succeeds on second try."""
    executor = RetryCountingExecutor(fail_count=1)
    planner = RePlanningPlanner()
    pipeline = AgentPipeline(
        planner=planner,
        executor=executor,
        validator=StrictValidator(),
        max_retries=2,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, ValidatedOutput)
    assert result.output.get("citations") is not None
    assert executor.attempts == 2


def test_self_correction_exhausts_retries() -> None:
    """Executor keeps failing, retries exhausted, final Rejection returned."""
    executor = RetryCountingExecutor(fail_count=99)
    planner = RePlanningPlanner()
    pipeline = AgentPipeline(
        planner=planner,
        executor=executor,
        validator=StrictValidator(),
        max_retries=2,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, Rejection)
    assert "missing_citations" in result.reasons


def test_non_retryable_rejection_skips_retry() -> None:
    """Non-retryable rejection returns immediately without retry."""
    executor = RetryCountingExecutor(fail_count=0)
    pipeline = AgentPipeline(
        executor=executor,
        validator=PermissionDeniedValidator(),
        max_retries=5,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, Rejection)
    assert "permission_denied" in result.reasons
    assert executor.attempts == 1  # only ran once


def test_pipeline_without_planner_no_self_correction() -> None:
    """Pipeline without Planner cannot self-correct, returns Rejection directly."""
    executor = RetryCountingExecutor(fail_count=1)
    pipeline = AgentPipeline(
        executor=executor,
        validator=StrictValidator(),
        max_retries=5,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, Rejection)
    assert executor.attempts == 1  # no retry without planner


def test_pipeline_without_validator_no_self_correction() -> None:
    """Pipeline without Validator has no rejection to trigger retry."""
    executor = RetryCountingExecutor(fail_count=1)
    pipeline = AgentPipeline(
        executor=executor,
        max_retries=5,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, RawResult)
    assert executor.attempts == 1


def test_max_retries_zero_means_no_retry() -> None:
    """max_retries=0 disables self-correction."""
    executor = RetryCountingExecutor(fail_count=1)
    planner = RePlanningPlanner()
    pipeline = AgentPipeline(
        planner=planner,
        executor=executor,
        validator=StrictValidator(),
        max_retries=0,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, Rejection)
    assert executor.attempts == 1


def test_successful_first_try_no_retry() -> None:
    """When first attempt passes validation, no retry occurs."""
    executor = RetryCountingExecutor(fail_count=0)
    planner = RePlanningPlanner()
    pipeline = AgentPipeline(
        planner=planner,
        executor=executor,
        validator=StrictValidator(),
        max_retries=5,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, ValidatedOutput)
    assert executor.attempts == 1
    assert planner.plan_count == 1
