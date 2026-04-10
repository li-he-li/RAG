"""
Tests for Contract Review Agent pipeline.

Covers: planner (template matching), executor (streaming diff analysis),
validator (findings consistency), full pipeline streaming, API contract.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import (
    ExecutionPlan,
    PlanStep,
    RawResult,
    ValidatedOutput,
)
from app.agents.contract_review import (
    ContractReviewExecutor,
    ContractReviewPlanner,
    ContractReviewValidator,
    create_contract_review_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan_input() -> dict[str, Any]:
    return {
        "session_id": "sess-cr-1",
        "template_id": "tpl-001",
        "query": "审查这份合同的风险条款",
        "db": MagicMock(),
    }


def _make_streaming_events() -> list[str]:
    """Produce NDJSON events matching the existing streaming contract."""
    return [
        json.dumps({"type": "start", "query": "审查合同", "review_mode": True,
                     "template_id": "tpl-001", "template_name": "标准合同",
                     "review_file_count": 1}, ensure_ascii=False) + "\n",
        json.dumps({"type": "file_start", "file_index": 0, "file_id": "f1",
                     "file_name": "contract.pdf", "template_id": "tpl-001",
                     "template_name": "标准合同", "finding_count": 2}, ensure_ascii=False) + "\n",
        json.dumps({"type": "delta", "delta": "## 风险分析\n", "file_index": 0,
                     "file_id": "f1", "file_name": "contract.pdf"}, ensure_ascii=False) + "\n",
        json.dumps({"type": "file_done", "file_index": 0, "file_id": "f1",
                     "file_name": "contract.pdf", "template_id": "tpl-001",
                     "template_name": "标准合同", "finding_count": 2}, ensure_ascii=False) + "\n",
        json.dumps({"type": "done", "query": "审查合同", "answer": "完整审查报告",
                     "review_mode": True, "template_id": "tpl-001",
                     "template_name": "标准合同", "review_file_count": 1}, ensure_ascii=False) + "\n",
    ]


async def _async_gen(lines: list[str]):
    for line in lines:
        yield line


# ---------------------------------------------------------------------------
# ContractReviewPlanner
# ---------------------------------------------------------------------------


class TestContractReviewPlanner:
    """Test that planner creates an execution plan from request input."""

    @pytest.mark.anyio
    async def test_planner_creates_execution_plan(self) -> None:
        planner = ContractReviewPlanner()
        result = await planner.run(_make_plan_input())

        assert isinstance(result, ExecutionPlan)
        assert len(result.steps) >= 1
        assert result.steps[0].target_agent == "contract_review_executor"

    @pytest.mark.anyio
    async def test_planner_extracts_session_and_template(self) -> None:
        planner = ContractReviewPlanner()
        result = await planner.run(_make_plan_input())

        # Plan metadata should carry session_id and template_id
        assert hasattr(result, "steps")
        step = result.steps[0]
        assert "session_id" in step.input_mapping
        assert "template_id" in step.input_mapping


# ---------------------------------------------------------------------------
# ContractReviewExecutor
# ---------------------------------------------------------------------------


class TestContractReviewExecutor:
    """Test that executor delegates to existing streaming service."""

    @pytest.mark.anyio
    async def test_executor_returns_raw_result_on_success(self) -> None:
        executor = ContractReviewExecutor()
        input_data = _make_plan_input()

        with patch(
            "app.agents.contract_review.generate_template_difference_review",
            new_callable=AsyncMock,
            return_value=[
                MagicMock(
                    file_id="f1",
                    file_name="contract.pdf",
                    template_id="tpl-001",
                    template_name="标准合同",
                    findings=[],
                    review_markdown="## 审查结果",
                ),
            ],
        ):
            result = await executor.run(input_data)
            assert isinstance(result, RawResult)
            assert result.status == "success"

    @pytest.mark.anyio
    async def test_executor_handles_error(self) -> None:
        executor = ContractReviewExecutor()
        input_data = _make_plan_input()

        with patch(
            "app.agents.contract_review.generate_template_difference_review",
            new_callable=AsyncMock,
            side_effect=RuntimeError("template not found"),
        ):
            result = await executor.run(input_data)
            assert isinstance(result, RawResult)
            assert result.status == "error"
            assert "template not found" in (result.error or "")


# ---------------------------------------------------------------------------
# ContractReviewValidator
# ---------------------------------------------------------------------------


class TestContractReviewValidator:
    """Test that validator checks findings consistency."""

    @pytest.mark.anyio
    async def test_validator_passes_valid_result(self) -> None:
        raw = RawResult(
            status="success",
            output=[
                {
                    "file_id": "f1",
                    "findings": [{"category": "missing_clause", "severity": "high"}],
                    "review_markdown": "## 审查结果",
                }
            ],
        )
        validator = ContractReviewValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        assert result.schema_name == "ContractReviewResponse"

    @pytest.mark.anyio
    async def test_validator_passes_empty_findings(self) -> None:
        raw = RawResult(
            status="success",
            output=[{"file_id": "f1", "findings": [], "review_markdown": "无差异"}],
        )
        validator = ContractReviewValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)

    @pytest.mark.anyio
    async def test_validator_handles_error_result(self) -> None:
        raw = RawResult(status="error", output=None, error="service error")
        validator = ContractReviewValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        assert result.metadata.get("error") == "service error"


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


class TestContractReviewPipeline:
    """Test the assembled [Planner → Executor → Validator] pipeline."""

    @pytest.mark.anyio
    async def test_pipeline_run_end_to_end(self) -> None:
        mock_result = [
            MagicMock(
                file_id="f1",
                file_name="contract.pdf",
                template_id="tpl-001",
                template_name="标准合同",
                findings=[],
                review_markdown="## 审查结果",
            ),
        ]
        # Make model_dump work on the mock
        for m in mock_result:
            m.model_dump = lambda self=m: {
                "file_id": self.file_id,
                "file_name": self.file_name,
                "template_id": self.template_id,
                "template_name": self.template_name,
                "findings": [],
                "review_markdown": self.review_markdown,
            }

        with patch(
            "app.agents.contract_review.generate_template_difference_review",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            pipeline = create_contract_review_pipeline()
            result = await pipeline.run(_make_plan_input())

            assert hasattr(result, "output") or hasattr(result, "schema_name")

    @pytest.mark.anyio
    async def test_pipeline_records_trajectory(self) -> None:
        from app.services.trajectory.logger import TrajectoryLogger

        mock_result = [
            MagicMock(
                file_id="f1", file_name="c.pdf", template_id="t1",
                template_name="T", findings=[], review_markdown="ok",
            ),
        ]
        for m in mock_result:
            m.model_dump = lambda self=m: {"file_id": self.file_id}

        with patch(
            "app.agents.contract_review.generate_template_difference_review",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            traj = TrajectoryLogger(session_id="sess-cr-traj")
            pipeline = create_contract_review_pipeline(trajectory_logger=traj)
            await pipeline.run(_make_plan_input())

            agent_names = [r["agent_name"] for r in traj.records]
            assert "contract_review_planner" in agent_names
            assert "contract_review_executor" in agent_names
            assert "contract_review_validator" in agent_names
            assert len(traj.records) == 3

    @pytest.mark.anyio
    async def test_pipeline_streaming_produces_events(self) -> None:
        events = _make_streaming_events()
        with patch(
            "app.agents.contract_review.stream_template_difference_review",
            return_value=_async_gen(events),
        ):
            pipeline = create_contract_review_pipeline()
            collected = []
            async for event in pipeline.stream(_make_plan_input()):
                collected.append(event)

            # Should produce NDJSON events (internal events filtered by adapter)
            assert len(collected) > 0
            # First non-internal event should be valid JSON
            for line in collected:
                if line.strip():
                    data = json.loads(line.strip())
                    assert "type" in data or "agent_name" in data
