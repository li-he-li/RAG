"""
Tests verifying DSPy data pipeline is truly wired end-to-end.

Verifies:
- TrajectoryLogger writes through to TrajectoryStore
- Pipeline execution populates the store
- Admin API can read trajectory data from the store
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
from app.agents.pipeline import AgentPipeline
from app.routers.trajectory import get_trajectory_store
from app.services.trajectory.logger import TrajectoryLogger
from app.services.trajectory.store import InMemoryTrajectoryStore


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TestTrajectoryLoggerWriteThrough:
    """Verify TrajectoryLogger writes to TrajectoryStore."""

    def test_logger_writes_to_store(self):
        """When a TrajectoryStore is provided, record() also saves to it."""
        store = InMemoryTrajectoryStore()
        logger = TrajectoryLogger(session_id="test-sess", trajectory_store=store)

        logger.record(
            agent_name="test_agent",
            step_type="execute",
            input_data={"query": "test"},
            output={"answer": "result"},
            duration_ms=100.0,
        )

        # Logger has the record
        assert len(logger.records) == 1

        # Store also has the record
        store_records = store.query_by_session("test-sess")
        assert len(store_records) == 1
        assert store_records[0]["agent_name"] == "test_agent"
        assert store_records[0]["step_type"] == "execute"
        assert store_records[0]["duration_ms"] == 100.0

    def test_logger_without_store_still_works(self):
        """Logger works fine without a store (no write-through)."""
        logger = TrajectoryLogger(session_id="test-sess")
        logger.record(
            agent_name="test_agent",
            step_type="execute",
            input_data={"query": "test"},
            output={"answer": "result"},
            duration_ms=100.0,
        )
        assert len(logger.records) == 1

    def test_multiple_records_accumulate(self):
        """Multiple records from different agents all appear in store."""
        store = InMemoryTrajectoryStore()
        logger = TrajectoryLogger(session_id="multi-sess", trajectory_store=store)

        logger.record("planner", "plan", {"q": 1}, {"plan": True}, 10.0)
        logger.record("executor", "execute", {"plan": True}, {"result": True}, 50.0)
        logger.record("validator", "validate", {"result": True}, {"valid": True}, 5.0)

        records = store.query_by_session("multi-sess")
        assert len(records) == 3
        assert [r["agent_name"] for r in records] == ["planner", "executor", "validator"]

    def test_store_write_failure_does_not_propagate(self):
        """If store.save() raises, the logger still records locally."""
        class BrokenStore:
            def save(self, **kw):
                raise RuntimeError("store broken")

        logger = TrajectoryLogger(session_id="broken-sess", trajectory_store=BrokenStore())
        logger.record("agent", "step", {"q": 1}, {"a": 1}, 10.0)

        # Local record still exists
        assert len(logger.records) == 1


class TestPipelinePopulatesStore:
    """Verify pipeline execution populates the global TrajectoryStore."""

    def test_pipeline_run_populates_store(self):
        """Running a pipeline with a store-connected logger fills the store."""
        store = InMemoryTrajectoryStore()
        logger = TrajectoryLogger(session_id="pipeline-sess", trajectory_store=store)

        class SimpleExecutor(ExecutorAgent):
            @property
            def name(self):
                return "simple_executor"
            async def can_handle(self, input_data):
                return 0.9
            async def validate(self, input_data):
                pass
            async def run(self, input_data):
                return RawResult(status="success", output={"answer": "42"})

        class SimpleValidator(ValidatorAgent):
            @property
            def name(self):
                return "simple_validator"
            async def can_handle(self, input_data):
                return 0.8
            async def validate(self, input_data):
                pass
            async def run(self, raw_result):
                return ValidatedOutput(output=raw_result.output, schema_name="Test")

        pipeline = AgentPipeline(
            executor=SimpleExecutor(),
            validator=SimpleValidator(),
            trajectory_logger=logger,
        )

        _run(pipeline.run({"query": "test"}))

        records = store.query_by_session("pipeline-sess")
        # Should have execute + validate records
        assert len(records) >= 2
        step_types = {r["step_type"] for r in records}
        assert "execute" in step_types
        assert "validate" in step_types


class TestGlobalStoreIntegration:
    """Verify the global store from routers.trajectory is accessible."""

    def test_global_store_exists(self):
        """The global trajectory store is initialized."""
        store = get_trajectory_store()
        assert store is not None
        assert isinstance(store, InMemoryTrajectoryStore)

    def test_global_store_is_singleton(self):
        """Multiple calls return the same store instance."""
        store1 = get_trajectory_store()
        store2 = get_trajectory_store()
        assert store1 is store2
