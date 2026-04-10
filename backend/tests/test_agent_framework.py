from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from app.agents import (
    AgentBase,
    AgentPipeline,
    ExecutionPlan,
    ExecutorAgent,
    PlanStep,
    PlannerAgent,
    RawResult,
    Rejection,
    SkillNotFoundError,
    SkillRegistry,
    ValidatedOutput,
    ValidationError,
    ValidatorAgent,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class EchoExecutor(ExecutorAgent[dict[str, Any], RawResult]):
    @property
    def name(self) -> str:
        return "echo_executor"

    async def validate(self, input_data: dict[str, Any]) -> None:
        if not isinstance(input_data, dict):
            raise ValidationError("input must be a dict")

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        return RawResult(
            status="success",
            output={"echo": input_data["value"]},
            intermediate_steps=[{"executor": self.name}],
        )


class PlanExecutor(ExecutorAgent[ExecutionPlan, RawResult]):
    @property
    def name(self) -> str:
        return "plan_executor"

    async def validate(self, input_data: ExecutionPlan) -> None:
        if not isinstance(input_data, ExecutionPlan):
            raise ValidationError("input must be an execution plan")

    async def run(self, input_data: ExecutionPlan) -> RawResult:
        outputs = []
        for step in input_data.steps:
            outputs.append({"step": step.name, "target": step.target_agent})
        return RawResult(
            status="success",
            output={"steps": outputs},
            intermediate_steps=outputs,
        )


class SimplePlanner(PlannerAgent[dict[str, Any], ExecutionPlan]):
    @property
    def name(self) -> str:
        return "simple_planner"

    async def validate(self, input_data: dict[str, Any]) -> None:
        if "value" not in input_data:
            raise ValidationError("value is required")

    async def run(self, input_data: dict[str, Any]) -> ExecutionPlan:
        return ExecutionPlan(
            steps=(
                PlanStep(
                    name="echo",
                    target_agent="plan_executor",
                    input_mapping={"value": input_data["value"]},
                    expected_output_type="dict",
                ),
            )
        )


class ApprovingValidator(ValidatorAgent[RawResult, ValidatedOutput | Rejection]):
    @property
    def name(self) -> str:
        return "approving_validator"

    async def validate(self, input_data: RawResult) -> None:
        if not isinstance(input_data, RawResult):
            raise ValidationError("input must be raw result")

    async def run(self, input_data: RawResult) -> ValidatedOutput | Rejection:
        if input_data.status != "success":
            return Rejection(reasons=("raw result failed",), details={"status": input_data.status})
        return ValidatedOutput(output=input_data.output, schema_name="dict")


class RejectingValidator(ApprovingValidator):
    @property
    def name(self) -> str:
        return "rejecting_validator"

    async def run(self, input_data: RawResult) -> ValidatedOutput | Rejection:
        return Rejection(reasons=("missing required field",), details={"field": "answer"})


class RecordingExecutor(EchoExecutor):
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        self.calls += 1
        await asyncio.sleep(0)
        return await super().run(input_data)


def _decode_events(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines]


def test_agent_base_rejects_invalid_input_before_run() -> None:
    executor = EchoExecutor()

    import pytest

    with pytest.raises(ValidationError):
        _run(executor.execute("not-a-dict"))


def test_minimal_executor_only_pipeline() -> None:
    pipeline = AgentPipeline(executor=EchoExecutor())

    result = _run(pipeline.run({"value": "hello"}))

    assert isinstance(result, RawResult)
    assert result.output == {"echo": "hello"}


def test_executor_validator_pipeline_returns_validated_output() -> None:
    pipeline = AgentPipeline(executor=EchoExecutor(), validator=ApprovingValidator())

    result = _run(pipeline.run({"value": "hello"}))

    assert isinstance(result, ValidatedOutput)
    assert result.output == {"echo": "hello"}
    assert result.schema_name == "dict"


def test_full_planner_executor_validator_pipeline() -> None:
    pipeline = AgentPipeline(
        planner=SimplePlanner(),
        executor=PlanExecutor(),
        validator=ApprovingValidator(),
    )

    result = _run(pipeline.run({"value": "hello"}))

    assert isinstance(result, ValidatedOutput)
    assert result.output == {"steps": [{"step": "echo", "target": "plan_executor"}]}


def test_pipeline_propagates_validator_rejection() -> None:
    pipeline = AgentPipeline(executor=EchoExecutor(), validator=RejectingValidator())

    result = _run(pipeline.run({"value": "hello"}))

    assert isinstance(result, Rejection)
    assert result.reasons == ("missing required field",)


async def _collect_stream(pipeline: AgentPipeline, payload: dict[str, Any]) -> list[str]:
    return [line async for line in pipeline.stream(payload)]


def test_pipeline_streams_topology_specific_ndjson_events() -> None:
    pipeline = AgentPipeline(
        planner=SimplePlanner(),
        executor=PlanExecutor(),
        validator=ApprovingValidator(),
    )

    events = _decode_events(_run(_collect_stream(pipeline, {"value": "hello"})))

    assert [event["type"] for event in events] == [
        "step_started",
        "plan_created",
        "step_completed",
        "step_started",
        "step_completed",
        "step_started",
        "validation_passed",
        "step_completed",
        "pipeline_completed",
    ]
    assert events[0]["agent_name"] == "simple_planner"
    assert events[3]["agent_name"] == "plan_executor"
    assert events[5]["agent_name"] == "approving_validator"


def test_simplified_stream_omits_planner_events() -> None:
    pipeline = AgentPipeline(executor=EchoExecutor(), validator=ApprovingValidator())

    events = _decode_events(_run(_collect_stream(pipeline, {"value": "hello"})))

    assert "plan_created" not in [event["type"] for event in events]
    assert events[0]["agent_name"] == "echo_executor"


async def _run_concurrent_pipeline(
    pipeline: AgentPipeline,
) -> list[RawResult | ValidatedOutput | Rejection]:
    return await asyncio.gather(
        pipeline.run({"value": "left"}),
        pipeline.run({"value": "right"}),
    )


def test_concurrent_invocations_are_independent() -> None:
    executor = RecordingExecutor()
    pipeline = AgentPipeline(executor=executor, validator=ApprovingValidator())

    results = _run(_run_concurrent_pipeline(pipeline))

    assert [result.output["echo"] for result in results if isinstance(result, ValidatedOutput)] == [
        "left",
        "right",
    ]
    assert executor.calls == 2


def test_skill_registry_register_discover_and_list_capabilities() -> None:
    registry = SkillRegistry()
    registry.register(
        "echo",
        EchoExecutor,
        {"description": "Echo executor", "role": "executor"},
    )

    entry = registry.discover("echo")

    assert entry.agent_class is EchoExecutor
    assert entry.metadata["description"] == "Echo executor"
    assert registry.list_capabilities() == [
        {"name": "echo", "description": "Echo executor", "role": "executor"}
    ]


def test_skill_registry_missing_skill_raises() -> None:
    import pytest

    registry = SkillRegistry()

    with pytest.raises(SkillNotFoundError):
        registry.discover("missing")
