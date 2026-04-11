"""
Tests for Opponent Prediction Agent pipeline.

Covers: planner, executor, validator, API contract compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.base import ExecutionPlan, RawResult, ValidatedOutput


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_contract" / "legacy_contracts.json"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _prediction_contract() -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return next(
        contract
        for contract in fixture["contracts"]
        if contract["endpoint"] == "/api/v1/opponent-prediction/start"
    )


def _make_prediction_report() -> dict[str, Any]:
    return _prediction_contract()["response"]


def _make_plan_input() -> dict[str, Any]:
    return {
        "session_id": "session-contract-001",
        "template_id": "prediction-template-001",
        "query": "Predict opponent arguments.",
        "db": MagicMock(),
    }


class TestPredictionPlanner:
    @pytest.mark.anyio
    async def test_planner_creates_execution_plan(self) -> None:
        from app.agents.opponent_prediction import PredictionPlanner

        planner = PredictionPlanner()
        result = await planner.run(_make_plan_input())

        assert isinstance(result, ExecutionPlan)
        assert len(result.steps) == 1
        assert result.steps[0].target_agent == "prediction_executor"
        assert result.steps[0].input_mapping["template_id"] == "prediction-template-001"


class TestPredictionExecutor:
    @pytest.mark.anyio
    async def test_executor_returns_raw_result_on_success(self) -> None:
        from app.agents.opponent_prediction import PredictionExecutor
        from app.models.schemas import OpponentPredictionReport

        report = OpponentPredictionReport.model_validate(_make_prediction_report())

        with patch(
            "app.agents.opponent_prediction.build_prediction_report",
            new_callable=AsyncMock,
            return_value=report,
        ) as mock_build:
            executor = PredictionExecutor()
            result = await executor.run(_make_plan_input())

        mock_build.assert_called_once()
        assert isinstance(result, RawResult)
        assert result.status == "success"
        assert result.output["report_id"] == "report-001"

    @pytest.mark.anyio
    async def test_executor_handles_service_error(self) -> None:
        from app.agents.opponent_prediction import PredictionExecutor

        with patch(
            "app.agents.opponent_prediction.build_prediction_report",
            new_callable=AsyncMock,
            side_effect=RuntimeError("prediction failed"),
        ):
            executor = PredictionExecutor()
            result = await executor.run(_make_plan_input())

        assert isinstance(result, RawResult)
        assert result.status == "error"
        assert "prediction failed" in (result.error or "")


class TestPredictionValidator:
    @pytest.mark.anyio
    async def test_validator_passes_valid_report(self) -> None:
        from app.agents.opponent_prediction import PredictionValidator

        raw = RawResult(status="success", output=_make_prediction_report())
        validator = PredictionValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        assert result.schema_name == "OpponentPredictionReport"
        assert result.metadata["predicted_argument_count"] == 1
        assert result.metadata["evidence_count"] == 1

    @pytest.mark.anyio
    async def test_validator_carries_error_metadata(self) -> None:
        from app.agents.opponent_prediction import PredictionValidator

        raw = RawResult(status="error", output=None, error="service error")
        validator = PredictionValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        assert result.metadata["error"] == "service error"


class TestPredictionPipeline:
    @pytest.mark.anyio
    async def test_pipeline_run_end_to_end(self) -> None:
        from app.agents.opponent_prediction import create_opponent_prediction_pipeline
        from app.models.schemas import OpponentPredictionReport

        report = OpponentPredictionReport.model_validate(_make_prediction_report())

        with patch(
            "app.agents.opponent_prediction.build_prediction_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            pipeline = create_opponent_prediction_pipeline()
            result = await pipeline.run(_make_plan_input())

        assert hasattr(result, "output")
        assert result.output["task_id"] == "task-001"

    @pytest.mark.anyio
    async def test_pipeline_records_trajectory(self) -> None:
        from app.agents.opponent_prediction import create_opponent_prediction_pipeline
        from app.models.schemas import OpponentPredictionReport
        from app.services.trajectory.logger import TrajectoryLogger

        report = OpponentPredictionReport.model_validate(_make_prediction_report())

        with patch(
            "app.agents.opponent_prediction.build_prediction_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            traj = TrajectoryLogger(session_id="sess-pred-traj")
            pipeline = create_opponent_prediction_pipeline(trajectory_logger=traj)
            await pipeline.run(_make_plan_input())

        agent_names = [record["agent_name"] for record in traj.records]
        assert agent_names == [
            "prediction_planner",
            "prediction_executor",
            "prediction_validator",
        ]

class TestPredictionCompatibility:
    @pytest.mark.anyio
    async def test_adapter_preserves_legacy_contract_for_route_migration(self) -> None:
        from app.agents.compatibility import CompatibilityAdapter, EndpointContract
        from app.agents.opponent_prediction import create_opponent_prediction_pipeline
        from app.models.schemas import OpponentPredictionReport

        report = OpponentPredictionReport.model_validate(_make_prediction_report())

        with patch(
            "app.agents.opponent_prediction.build_prediction_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            pipeline = create_opponent_prediction_pipeline()
            result = await pipeline.run(_make_plan_input())

        adapter = CompatibilityAdapter(
            EndpointContract(
                name="opponent_prediction_start",
                response_mapper=lambda output: output if isinstance(output, dict) else {},
                public_stream_event_types=frozenset(),
            )
        )

        assert adapter.adapt_response(result) == report.model_dump(mode="json")


class TestPredictionRouter:
    def _create_app(self) -> FastAPI:
        from app.core.database import get_session
        from app.routers.prediction import router as prediction_router

        app = FastAPI()
        app.dependency_overrides[get_session] = lambda: MagicMock()
        app.include_router(prediction_router, prefix="/api/v1")
        return app

    def test_route_preserves_legacy_contract_via_agent_pipeline(self) -> None:
        from app.models.schemas import OpponentPredictionReport

        report = OpponentPredictionReport.model_validate(_make_prediction_report())
        client = TestClient(self._create_app())

        with patch(
            "app.agents.opponent_prediction.build_prediction_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            response = client.post(
                "/api/v1/opponent-prediction/start",
                json={
                    "session_id": "session-contract-001",
                    "template_id": "prediction-template-001",
                    "query": "Predict opponent arguments.",
                },
            )

        assert response.status_code == 200
        assert response.json() == report.model_dump(mode="json")
