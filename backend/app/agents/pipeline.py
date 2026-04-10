from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from app.agents.base import (
    AgentBase,
    ExecutionPlan,
    ExecutorAgent,
    PlannerAgent,
    RawResult,
    Rejection,
    ValidatedOutput,
    ValidatorAgent,
)
from app.agents.output_governance import (
    GovernanceBlockError,
    OutputGovernancePipeline,
    SchemaValidationError,
)

if TYPE_CHECKING:
    from app.services.trajectory.logger import TrajectoryLogger

logger = logging.getLogger(__name__)


class AgentPipeline:
    def __init__(
        self,
        *,
        executor: ExecutorAgent[Any, Any],
        planner: PlannerAgent[Any, ExecutionPlan] | None = None,
        validator: ValidatorAgent[Any, ValidatedOutput | Rejection] | None = None,
        governance_pipeline: OutputGovernancePipeline | None = None,
        trajectory_logger: TrajectoryLogger | None = None,
        prompt_versions: dict[str, str] | None = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.validator = validator
        self.governance_pipeline = governance_pipeline or OutputGovernancePipeline()
        self._trajectory_logger = trajectory_logger
        self._prompt_versions = prompt_versions or {}
        self._ensure_unique_agent_names()

    async def run(self, request: Any) -> RawResult | ValidatedOutput | Rejection:
        current: Any = request
        if self.planner is not None:
            t0 = time.monotonic()
            current = await self.planner.execute(current)
            self._record_trajectory(self.planner, "plan", request, current, t0)

        t0 = time.monotonic()
        raw_result = await self.executor.execute(current)
        self._record_trajectory(self.executor, "execute", current, raw_result, t0)

        if self.validator is None:
            await self.governance_pipeline.govern_raw_result(raw_result)
            return raw_result

        t0 = time.monotonic()
        validated = await self.validator.execute(raw_result)
        self._record_trajectory(self.validator, "validate", raw_result, validated, t0)

        if isinstance(validated, Rejection):
            return validated
        return await self.governance_pipeline.govern_output(validated)

    async def stream(self, request: Any) -> AsyncIterator[str]:
        current: Any = request
        if self.planner is not None:
            yield self._event("step_started", self.planner)
            t0 = time.monotonic()
            current = await self.planner.execute(current)
            self._record_trajectory(self.planner, "plan", request, current, t0)
            yield self._event(
                "plan_created",
                self.planner,
                {"step_count": len(current.steps)},
            )
            yield self._event("step_completed", self.planner)

        yield self._event("step_started", self.executor)
        t0 = time.monotonic()
        raw_result = await self.executor.execute(current)
        self._record_trajectory(self.executor, "execute", current, raw_result, t0)
        yield self._event(
            "step_completed",
            self.executor,
            {"status": getattr(raw_result, "status", "success")},
        )

        if self.validator is None:
            try:
                await self.governance_pipeline.govern_raw_result(raw_result, layer="post_stream")
            except (GovernanceBlockError, SchemaValidationError) as exc:
                yield self.governance_pipeline.retracted_event(
                    violated_rule=exc.violated_rule,
                    message="discard prior streamed content",
                )
                return
            yield self._event("pipeline_completed", self.executor)
            return

        yield self._event("step_started", self.validator)
        t0 = time.monotonic()
        validated = await self.validator.execute(raw_result)
        self._record_trajectory(self.validator, "validate", raw_result, validated, t0)
        if isinstance(validated, Rejection):
            yield self._event(
                "validation_rejected",
                self.validator,
                {"reasons": list(validated.reasons), "details": validated.details},
            )
            yield self._event("step_completed", self.validator)
            yield self._event("pipeline_completed", self.validator, {"status": "rejected"})
            return

        try:
            validated = await self.governance_pipeline.govern_output(
                validated,
                layer="post_stream",
            )
        except (GovernanceBlockError, SchemaValidationError) as exc:
            yield self.governance_pipeline.retracted_event(
                violated_rule=exc.violated_rule,
                message="discard prior streamed content",
            )
            return

        yield self._event(
            "validation_passed",
            self.validator,
            {"schema_name": validated.schema_name},
        )
        yield self._event("step_completed", self.validator)
        yield self._event("pipeline_completed", self.validator)

    def _ensure_unique_agent_names(self) -> None:
        agents = [agent for agent in (self.planner, self.executor, self.validator) if agent]
        names = [agent.name for agent in agents]
        if len(names) != len(set(names)):
            raise ValueError("agent names must be unique within a pipeline")

    def _record_trajectory(
        self,
        agent: AgentBase[Any, Any],
        step_type: str,
        input_data: Any,
        output: Any,
        start_time: float,
    ) -> None:
        """Record a trajectory entry for an agent step, if logger is configured."""
        if self._trajectory_logger is None:
            return
        duration_ms = (time.monotonic() - start_time) * 1000
        try:
            self._trajectory_logger.record(
                agent_name=agent.name,
                step_type=step_type,
                input_data=input_data,
                output=output,
                duration_ms=duration_ms,
                prompt_versions=self._prompt_versions,
            )
        except Exception as exc:
            logger.warning("trajectory recording failed for %s: %s", agent.name, exc)

    @staticmethod
    def _event(
        event_type: str,
        agent: AgentBase[Any, Any],
        payload: dict[str, Any] | None = None,
    ) -> str:
        return json.dumps(
            {
                "type": event_type,
                "agent_name": agent.name,
                "payload": payload or {},
            },
            ensure_ascii=False,
        ) + "\n"
