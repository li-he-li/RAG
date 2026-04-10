from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

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


class AgentPipeline:
    def __init__(
        self,
        *,
        executor: ExecutorAgent[Any, Any],
        planner: PlannerAgent[Any, ExecutionPlan] | None = None,
        validator: ValidatorAgent[Any, ValidatedOutput | Rejection] | None = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.validator = validator
        self._ensure_unique_agent_names()

    async def run(self, request: Any) -> RawResult | ValidatedOutput | Rejection:
        current: Any = request
        if self.planner is not None:
            current = await self.planner.execute(current)
        raw_result = await self.executor.execute(current)
        if self.validator is None:
            return raw_result
        return await self.validator.execute(raw_result)

    async def stream(self, request: Any) -> AsyncIterator[str]:
        current: Any = request
        if self.planner is not None:
            yield self._event("step_started", self.planner)
            current = await self.planner.execute(current)
            yield self._event(
                "plan_created",
                self.planner,
                {"step_count": len(current.steps)},
            )
            yield self._event("step_completed", self.planner)

        yield self._event("step_started", self.executor)
        raw_result = await self.executor.execute(current)
        yield self._event(
            "step_completed",
            self.executor,
            {"status": getattr(raw_result, "status", "success")},
        )

        if self.validator is None:
            yield self._event("pipeline_completed", self.executor)
            return

        yield self._event("step_started", self.validator)
        validated = await self.validator.execute(raw_result)
        if isinstance(validated, Rejection):
            yield self._event(
                "validation_rejected",
                self.validator,
                {"reasons": list(validated.reasons), "details": validated.details},
            )
            yield self._event("step_completed", self.validator)
            yield self._event("pipeline_completed", self.validator, {"status": "rejected"})
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
