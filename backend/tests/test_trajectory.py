"""
Tests for trajectory logging service.

Covers: recording, querying, replay, data governance (redaction, TTL),
prompt version snapshot, async non-blocking writes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from app.agents.base import (
    ExecutionPlan,
    ExecutorAgent,
    PlanStep,
    PlannerAgent,
    RawResult,
    ValidatedOutput,
    ValidatorAgent,
)
from app.services.trajectory.logger import TrajectoryLogger
from app.services.trajectory.governance import (
    DataGovernancePolicy,
    RedactionRule,
    default_governance_policy,
)
from app.services.trajectory.replay import TrajectoryReplayService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeExecutor(ExecutorAgent[Any, Any]):
    @property
    def name(self) -> str:
        return "test_executor"

    async def run(self, input_data: Any) -> RawResult:
        return RawResult(status="success", output={"answer": "42"})


class FakeValidator(ValidatorAgent[Any, Any]):
    @property
    def name(self) -> str:
        return "test_validator"

    async def run(self, input_data: Any) -> ValidatedOutput:
        return ValidatedOutput(output={"answer": "42"}, schema_name="test_schema")


# ---------------------------------------------------------------------------
# TrajectoryLogger — recording
# ---------------------------------------------------------------------------


class TestTrajectoryRecording:
    """Test that each agent step produces a well-formed trajectory record."""

    def test_record_planner_step(self) -> None:
        logger = TrajectoryLogger(session_id="sess-1")
        plan = ExecutionPlan(
            steps=(PlanStep(name="step1", target_agent="executor"),)
        )
        logger.record(
            agent_name="planner",
            step_type="plan",
            input_data={"query": "search cases"},
            output=plan,
            duration_ms=50.0,
            token_usage={"prompt": 100, "completion": 50},
        )

        records = logger.records
        assert len(records) == 1
        r = records[0]
        assert r["session_id"] == "sess-1"
        assert r["agent_name"] == "planner"
        assert r["step_type"] == "plan"
        assert r["duration_ms"] == 50.0
        assert r["token_usage"] == {"prompt": 100, "completion": 50}

    def test_record_executor_step(self) -> None:
        logger = TrajectoryLogger(session_id="sess-2")
        logger.record(
            agent_name="executor",
            step_type="execute",
            input_data={"plan": "step1"},
            output=RawResult(status="success", output={"answer": "42"}),
            duration_ms=120.0,
        )

        records = logger.records
        assert len(records) == 1
        assert records[0]["agent_name"] == "executor"
        assert records[0]["step_type"] == "execute"

    def test_record_validator_step(self) -> None:
        logger = TrajectoryLogger(session_id="sess-3")
        logger.record(
            agent_name="validator",
            step_type="validate",
            input_data={"result": "raw"},
            output=ValidatedOutput(output={"answer": "42"}, schema_name="test"),
            duration_ms=30.0,
        )

        records = logger.records
        assert len(records) == 1
        assert records[0]["agent_name"] == "validator"
        assert records[0]["step_type"] == "validate"

    def test_input_hash_is_deterministic(self) -> None:
        logger = TrajectoryLogger(session_id="sess-hash")
        input_data = {"query": "deterministic hash test"}

        logger.record("executor", "execute", input_data, None, 10.0)
        logger.record("executor", "execute", input_data, None, 10.0)

        assert len(logger.records) == 2
        assert logger.records[0]["input_hash"] == logger.records[1]["input_hash"]

    def test_input_hash_uses_sha256(self) -> None:
        logger = TrajectoryLogger(session_id="sess-sha")
        input_data = {"key": "value"}
        expected = hashlib.sha256(
            json.dumps(input_data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

        logger.record("executor", "execute", input_data, None, 10.0)
        assert logger.records[0]["input_hash"] == expected

    def test_multiple_records_ordered(self) -> None:
        logger = TrajectoryLogger(session_id="sess-order")
        for i in range(5):
            logger.record(f"agent_{i}", "execute", {"i": i}, None, float(i))

        records = logger.records
        assert len(records) == 5
        for i, r in enumerate(records):
            assert r["agent_name"] == f"agent_{i}"


# ---------------------------------------------------------------------------
# Data governance — redaction + TTL
# ---------------------------------------------------------------------------


class TestDataGovernance:
    """Test default redaction, full-text opt-in, and TTL cleanup."""

    def test_default_policy_redacts_sensitive_fields(self) -> None:
        policy = default_governance_policy()
        data = {
            "query": "legal search",
            "user_phone": "13800138000",
            "user_email": "test@example.com",
            "id_number": "110101199001011234",
        }
        result = policy.apply(data)
        assert result["query"] == "legal search"
        assert result["user_phone"] != "13800138000"
        assert result["user_email"] != "test@example.com"
        assert result["id_number"] != "110101199001011234"

    def test_redaction_rule_replaces_with_mask(self) -> None:
        rule = RedactionRule(field_pattern=r"phone", replacement="[REDACTED]")
        data = {"user_phone": "13800138000", "name": "Zhang"}
        result = rule.apply(data)
        assert result["user_phone"] == "[REDACTED]"
        assert result["name"] == "Zhang"

    def test_full_text_requires_explicit_opt_in(self) -> None:
        policy = default_governance_policy()
        assert policy.full_text_enabled is False

        # Without opt-in, output should be summarized, not full text
        output = {"long_text": "x" * 1000, "safe_field": "ok"}
        result = policy.apply(output)
        assert len(str(result.get("long_text", ""))) < 1000 or result.get("long_text") == "[REDACTED]"

    def test_ttl_cleanup_removes_expired_records(self) -> None:
        logger = TrajectoryLogger(session_id="sess-ttl")
        # Add a record and manually backdate it
        logger.record("executor", "execute", {"i": 1}, None, 10.0)
        logger.records[0]["created_at"] = datetime.now(UTC) - timedelta(days=31)

        removed = logger.cleanup_expired(ttl_days=30)
        assert removed == 1
        assert len(logger.records) == 0

    def test_ttl_cleanup_keeps_fresh_records(self) -> None:
        logger = TrajectoryLogger(session_id="sess-fresh")
        logger.record("executor", "execute", {"i": 1}, None, 10.0)

        removed = logger.cleanup_expired(ttl_days=30)
        assert removed == 0
        assert len(logger.records) == 1


# ---------------------------------------------------------------------------
# Prompt version snapshot
# ---------------------------------------------------------------------------


class TestPromptSnapshot:
    """Test that prompt versions are captured with trajectory records."""

    def test_prompt_versions_included_in_record(self) -> None:
        logger = TrajectoryLogger(session_id="sess-prompt")
        prompt_versions = {
            "similar_case_search": "1.0.0",
            "retrieval_explanation": "2.1.0",
        }

        logger.record(
            "executor",
            "execute",
            {"query": "test"},
            None,
            100.0,
            prompt_versions=prompt_versions,
        )

        record = logger.records[0]
        assert record["prompt_versions"] == prompt_versions

    def test_prompt_versions_default_to_empty(self) -> None:
        logger = TrajectoryLogger(session_id="sess-no-prompt")
        logger.record("executor", "execute", {"q": "x"}, None, 10.0)

        assert logger.records[0]["prompt_versions"] == {}


# ---------------------------------------------------------------------------
# Async non-blocking write
# ---------------------------------------------------------------------------


class TestAsyncNonBlocking:
    """Test that trajectory writes don't block pipeline execution."""

    def test_write_does_not_block(self) -> None:
        logger = TrajectoryLogger(session_id="sess-async")

        # Simulate pipeline step completing
        start = time.monotonic()
        logger.record("executor", "execute", {"q": "test"}, {"a": "42"}, 5.0)
        elapsed = time.monotonic() - start

        # Recording should be near-instant (in-memory)
        assert elapsed < 0.1

    def test_write_failure_does_not_propagate(self) -> None:
        logger = TrajectoryLogger(session_id="sess-fail")

        # record() should never raise, even with bad input
        try:
            logger.record("executor", "execute", None, None, 10.0)
            logger.record("executor", "execute", {"unserializable": object()}, None, 10.0)
        except Exception:
            pytest.fail("TrajectoryLogger.record() should not raise exceptions")


# ---------------------------------------------------------------------------
# Trajectory query (in-memory, DB-free tests)
# ---------------------------------------------------------------------------


class TestTrajectoryQuery:
    """Test querying trajectory records by session_id."""

    def test_query_by_session_id(self) -> None:
        logger = TrajectoryLogger(session_id="sess-query")
        for i in range(3):
            logger.record(f"agent_{i}", "execute", {"i": i}, None, float(i))

        records = logger.query(session_id="sess-query")
        assert len(records) == 3

    def test_query_returns_empty_for_unknown_session(self) -> None:
        logger = TrajectoryLogger(session_id="sess-known")
        logger.record("executor", "execute", {}, None, 10.0)

        records = logger.query(session_id="nonexistent")
        assert records == []

    def test_query_preserves_chronological_order(self) -> None:
        logger = TrajectoryLogger(session_id="sess-order-q")
        names = ["planner", "executor", "validator"]
        for name in names:
            logger.record(name, "step", {"n": name}, None, 10.0)

        records = logger.query(session_id="sess-order-q")
        assert [r["agent_name"] for r in records] == names


# ---------------------------------------------------------------------------
# Pipeline replay
# ---------------------------------------------------------------------------


class TestPipelineReplay:
    """Test reconstructing a full pipeline run from trajectory records."""

    def test_replay_reconstructs_full_chain(self) -> None:
        logger = TrajectoryLogger(session_id="sess-replay")
        logger.record("planner", "plan", {"query": "test"}, {"plan": "step1"}, 50.0)
        logger.record("executor", "execute", {"plan": "step1"}, {"answer": "42"}, 100.0)
        logger.record("validator", "validate", {"answer": "42"}, {"validated": True}, 30.0)

        replay = TrajectoryReplayService.replay(logger.records)
        assert replay["session_id"] == "sess-replay"
        assert replay["step_count"] == 3
        assert replay["steps"][0]["agent_name"] == "planner"
        assert replay["steps"][2]["agent_name"] == "validator"
        assert replay["status"] == "completed"

    def test_replay_identifies_failure_point(self) -> None:
        logger = TrajectoryLogger(session_id="sess-fail-replay")
        logger.record("planner", "plan", {"query": "test"}, {"plan": "step1"}, 50.0)
        logger.record("executor", "execute", {"plan": "step1"}, {"error": "timeout"}, 100.0, error="timeout")

        replay = TrajectoryReplayService.replay(logger.records)
        assert replay["status"] == "failed"
        assert replay["failed_step"] == "executor"
        assert replay["steps"][-1].get("error") == "timeout"

    def test_replay_validates_output_integrity(self) -> None:
        logger = TrajectoryLogger(session_id="sess-integrity")
        logger.record("planner", "plan", {"q": "test"}, {"plan": "step1"}, 10.0)
        logger.record("executor", "execute", {"plan": "step1"}, {"result": "data"}, 20.0)

        replay = TrajectoryReplayService.replay(logger.records)
        # planner output should feed into executor input
        assert replay.get("validation_warnings") is not None


# ---------------------------------------------------------------------------
# Pipeline integration — trajectory auto-recording
# ---------------------------------------------------------------------------


class TestPipelineTrajectoryIntegration:
    """Test that AgentPipeline automatically records trajectory for each step."""

    @pytest.mark.anyio
    async def test_executor_only_pipeline_records_one_step(self) -> None:
        from app.agents.pipeline import AgentPipeline
        from app.agents.base import ExecutorAgent, RawResult

        class SimpleExecutor(ExecutorAgent):
            @property
            def name(self) -> str:
                return "simple_executor"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return RawResult(status="success", output={"result": "done"})

        traj_logger = TrajectoryLogger(session_id="sess-pipe-1")
        pipeline = AgentPipeline(
            executor=SimpleExecutor(),
            trajectory_logger=traj_logger,
        )
        result = await pipeline.run({"query": "test"})

        records = traj_logger.records
        assert len(records) == 1
        assert records[0]["agent_name"] == "simple_executor"
        assert records[0]["step_type"] == "execute"
        assert records[0]["duration_ms"] >= 0

    @pytest.mark.anyio
    async def test_executor_validator_pipeline_records_two_steps(self) -> None:
        from app.agents.pipeline import AgentPipeline
        from app.agents.base import ExecutorAgent, ValidatorAgent, RawResult, ValidatedOutput

        class Exe(ExecutorAgent):
            @property
            def name(self) -> str:
                return "exe"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return RawResult(status="success", output={"val": 1})

        class Val(ValidatorAgent):
            @property
            def name(self) -> str:
                return "val"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return ValidatedOutput(output={"val": 1}, schema_name="test")

        traj_logger = TrajectoryLogger(session_id="sess-pipe-2")
        pipeline = AgentPipeline(
            executor=Exe(),
            validator=Val(),
            trajectory_logger=traj_logger,
        )
        await pipeline.run({"query": "test"})

        records = traj_logger.records
        assert len(records) == 2
        assert records[0]["agent_name"] == "exe"
        assert records[0]["step_type"] == "execute"
        assert records[1]["agent_name"] == "val"
        assert records[1]["step_type"] == "validate"

    @pytest.mark.anyio
    async def test_full_pipeline_records_three_steps(self) -> None:
        from app.agents.pipeline import AgentPipeline
        from app.agents.base import (
            ExecutorAgent, PlannerAgent, ValidatorAgent,
            ExecutionPlan, PlanStep, RawResult, ValidatedOutput,
        )

        class Plan(PlannerAgent):
            @property
            def name(self) -> str:
                return "plan"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return ExecutionPlan(
                    steps=(PlanStep(name="step1", target_agent="exe"),)
                )

        class Exe(ExecutorAgent):
            @property
            def name(self) -> str:
                return "exe"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return RawResult(status="success", output={"x": 1})

        class Val(ValidatorAgent):
            @property
            def name(self) -> str:
                return "val"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return ValidatedOutput(output={"x": 1}, schema_name="test")

        traj_logger = TrajectoryLogger(session_id="sess-pipe-3")
        pipeline = AgentPipeline(
            executor=Exe(),
            planner=Plan(),
            validator=Val(),
            trajectory_logger=traj_logger,
        )
        await pipeline.run({"query": "full pipeline"})

        records = traj_logger.records
        assert len(records) == 3
        names = [r["agent_name"] for r in records]
        assert names == ["plan", "exe", "val"]
        types = [r["step_type"] for r in records]
        assert types == ["plan", "execute", "validate"]

    @pytest.mark.anyio
    async def test_pipeline_without_trajectory_logger_works(self) -> None:
        """Pipeline without trajectory_logger should work as before (backward compat)."""
        from app.agents.pipeline import AgentPipeline
        from app.agents.base import ExecutorAgent, RawResult

        class Exe(ExecutorAgent):
            @property
            def name(self) -> str:
                return "exe"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return RawResult(status="success", output={"ok": True})

        pipeline = AgentPipeline(executor=Exe())
        result = await pipeline.run({"query": "test"})
        assert result.status == "success"

    @pytest.mark.anyio
    async def test_pipeline_records_prompt_versions(self) -> None:
        from app.agents.pipeline import AgentPipeline
        from app.agents.base import ExecutorAgent, RawResult

        class Exe(ExecutorAgent):
            @property
            def name(self) -> str:
                return "exe"

            async def validate(self, input_data):
                pass

            async def run(self, input_data):
                return RawResult(status="success", output={"ok": True})

        traj_logger = TrajectoryLogger(session_id="sess-prompt-ver")
        pipeline = AgentPipeline(
            executor=Exe(),
            trajectory_logger=traj_logger,
            prompt_versions={"chat": "1.2.0", "retrieval": "2.0.0"},
        )
        await pipeline.run({"query": "test"})

        records = traj_logger.records
        assert records[0]["prompt_versions"] == {"chat": "1.2.0", "retrieval": "2.0.0"}


# ---------------------------------------------------------------------------
# Trajectory Store — DB persistence layer
# ---------------------------------------------------------------------------


class TestTrajectoryStore:
    """Test TrajectoryStore persists and queries records via SQLAlchemy."""

    def test_store_persists_record_to_db(self) -> None:
        from app.services.trajectory.store import TrajectoryStore, InMemoryTrajectoryStore

        store = InMemoryTrajectoryStore()
        store.save(
            session_id="sess-store-1",
            agent_name="executor",
            step_type="execute",
            input_hash="abc123",
            output={"result": "done"},
            duration_ms=50.0,
            token_usage={"prompt": 100, "completion": 50},
            prompt_versions={"chat": "1.0.0"},
        )

        records = store.query_by_session("sess-store-1")
        assert len(records) == 1
        assert records[0]["session_id"] == "sess-store-1"
        assert records[0]["agent_name"] == "executor"
        assert records[0]["output"] == {"result": "done"}

    def test_store_query_returns_empty_for_unknown_session(self) -> None:
        from app.services.trajectory.store import InMemoryTrajectoryStore

        store = InMemoryTrajectoryStore()
        assert store.query_by_session("nonexistent") == []

    def test_store_query_preserves_order(self) -> None:
        from app.services.trajectory.store import InMemoryTrajectoryStore

        store = InMemoryTrajectoryStore()
        for i, name in enumerate(["planner", "executor", "validator"]):
            store.save(
                session_id="sess-order",
                agent_name=name,
                step_type="step",
                input_hash=f"hash_{i}",
                output={"i": i},
                duration_ms=float(i),
            )

        records = store.query_by_session("sess-order")
        assert [r["agent_name"] for r in records] == ["planner", "executor", "validator"]

    def test_store_cleanup_removes_expired(self) -> None:
        from app.services.trajectory.store import InMemoryTrajectoryStore

        store = InMemoryTrajectoryStore()
        store.save("sess-old", "exe", "execute", "h", {}, 10.0)
        # Backdate the record (store uses ISO string)
        store._records[0]["created_at"] = (
            datetime.now(UTC) - timedelta(days=31)
        ).isoformat()

        removed = store.cleanup_expired(ttl_days=30)
        assert removed == 1
        assert store.query_by_session("sess-old") == []


# ---------------------------------------------------------------------------
# Trajectory API endpoint
# ---------------------------------------------------------------------------


class TestTrajectoryAPI:
    """Test GET /api/v1/trajectories/{session_id} endpoint."""

    def _create_app(self):
        """Create a test FastAPI app with trajectory router."""
        from fastapi import FastAPI
        from app.routers.trajectory import router as trajectory_router
        from app.services.trajectory.store import InMemoryTrajectoryStore

        app = FastAPI()
        store = InMemoryTrajectoryStore()
        # Seed some data
        store.save("sess-api-1", "planner", "plan", "h1", {"plan": "step1"}, 50.0,
                    token_usage={"prompt": 100}, prompt_versions={"chat": "1.0.0"})
        store.save("sess-api-1", "executor", "execute", "h2", {"result": "data"}, 100.0,
                    token_usage={"prompt": 200, "completion": 50})
        store.save("sess-api-2", "executor", "execute", "h3", {"result": "other"}, 30.0)

        # Override the store dependency
        from app.routers.trajectory import get_trajectory_store
        app.dependency_overrides[get_trajectory_store] = lambda: store
        app.include_router(trajectory_router, prefix="/api/v1")
        return app

    def test_get_trajectories_returns_records(self) -> None:
        app = self._create_app()
        client = TestClient(app)

        resp = client.get("/api/v1/trajectories/sess-api-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["agent_name"] == "planner"
        assert data[1]["agent_name"] == "executor"

    def test_get_trajectories_includes_all_fields(self) -> None:
        app = self._create_app()
        client = TestClient(app)

        resp = client.get("/api/v1/trajectories/sess-api-1")
        record = resp.json()[0]
        for field in ("session_id", "agent_name", "step_type", "input_hash",
                       "output", "duration_ms", "token_usage", "created_at"):
            assert field in record, f"missing field: {field}"

    def test_get_trajectories_empty_session_returns_200(self) -> None:
        app = self._create_app()
        client = TestClient(app)

        resp = client.get("/api/v1/trajectories/nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_trajectories_replay_endpoint(self) -> None:
        app = self._create_app()
        client = TestClient(app)

        resp = client.get("/api/v1/trajectories/sess-api-1/replay")
        assert resp.status_code == 200
        replay = resp.json()
        assert replay["session_id"] == "sess-api-1"
        assert replay["step_count"] == 2
        assert replay["status"] == "completed"
