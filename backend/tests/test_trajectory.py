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
