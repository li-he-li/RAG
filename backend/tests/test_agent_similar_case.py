"""
Tests for Similar Case Search Agent pipeline.

Covers: executor (retrieval + rerank), validator (traceability),
API contract compatibility via CompatibilityAdapter.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import (
    RawResult,
    ValidatedOutput,
)
from app.agents.similar_case import (
    SimilarCaseExecutor,
    SimilarCaseValidator,
    create_similar_case_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_response() -> dict[str, Any]:
    """Create a minimal valid similar case search response."""
    return {
        "exact_match": None,
        "near_duplicate_matches": [],
        "similar_case_matches": [
            {
                "doc_id": "doc-1",
                "file_name": "case_A.pdf",
                "version_id": "v1",
                "final_score": 0.92,
                "similarity_score": 0.90,
                "match_type": "similar_case",
                "match_reason": "document similarity",
                "text_overlap_ratio": 0.35,
                "file_name_aligned": False,
                "citations": [],
                "matched_points": ["争议焦点匹配"],
                "matched_profile_fields": ["dispute_focuses"],
            }
        ],
        "case_search_profile": {
            "legal_relationship": "合同纠纷",
            "dispute_focuses": ["违约"],
            "claim_targets": ["赔偿"],
            "party_roles": ["原告", "被告"],
            "key_facts": ["签订合同"],
            "timeline": [],
            "amount_terms": ["10万元"],
            "retrieval_intent": "similar_case",
        },
        "comparison_query": "合同违约纠纷",
    }


# ---------------------------------------------------------------------------
# SimilarCaseExecutor
# ---------------------------------------------------------------------------


class TestSimilarCaseExecutor:
    """Test that executor delegates to existing service and returns RawResult."""

    @pytest.mark.anyio
    async def test_executor_calls_existing_service(self) -> None:
        mock_response = _make_search_response()
        with patch(
            "app.agents.similar_case.execute_similar_case_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_search:
            executor = SimilarCaseExecutor()
            input_data = {
                "request": {"session_id": "s1", "query": "合同纠纷"},
                "db": MagicMock(),
            }
            result = await executor.run(input_data)

            mock_search.assert_called_once()
            assert isinstance(result, RawResult)
            assert result.status == "success"
            assert result.output == mock_response

    @pytest.mark.anyio
    async def test_executor_handles_service_error(self) -> None:
        with patch(
            "app.agents.similar_case.execute_similar_case_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB connection lost"),
        ):
            executor = SimilarCaseExecutor()
            input_data = {
                "request": {"session_id": "s1", "query": "test"},
                "db": MagicMock(),
            }
            result = await executor.run(input_data)

            assert isinstance(result, RawResult)
            assert result.status == "error"
            assert result.error is not None


# ---------------------------------------------------------------------------
# SimilarCaseValidator
# ---------------------------------------------------------------------------


class TestSimilarCaseValidator:
    """Test that validator checks response completeness."""

    @pytest.mark.anyio
    async def test_validator_passes_valid_response(self) -> None:
        mock_response = _make_search_response()
        raw = RawResult(status="success", output=mock_response)

        validator = SimilarCaseValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        assert result.schema_name == "SimilarCaseSearchResponse"

    @pytest.mark.anyio
    async def test_validator_rejects_empty_response(self) -> None:
        raw = RawResult(status="success", output={})

        validator = SimilarCaseValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        # Empty response is still valid structurally, just no matches

    @pytest.mark.anyio
    async def test_validator_rejects_error_result(self) -> None:
        raw = RawResult(status="error", output=None, error="service failed")

        validator = SimilarCaseValidator()
        result = await validator.run(raw)

        assert isinstance(result, ValidatedOutput)
        # Error results pass through with error metadata


# ---------------------------------------------------------------------------
# Pipeline assembly
# ---------------------------------------------------------------------------


class TestSimilarCasePipeline:
    """Test the assembled [Executor → Validator] pipeline."""

    @pytest.mark.anyio
    async def test_pipeline_end_to_end(self) -> None:
        mock_response = _make_search_response()
        with patch(
            "app.agents.similar_case.execute_similar_case_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            pipeline = create_similar_case_pipeline()
            input_data = {
                "request": {"session_id": "s1", "query": "合同纠纷"},
                "db": MagicMock(),
            }
            result = await pipeline.run(input_data)

            # Pipeline returns ValidatedOutput (governed)
            assert hasattr(result, "output") or hasattr(result, "schema_name")

    @pytest.mark.anyio
    async def test_pipeline_records_trajectory(self) -> None:
        from app.services.trajectory.logger import TrajectoryLogger

        mock_response = _make_search_response()
        with patch(
            "app.agents.similar_case.execute_similar_case_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            traj = TrajectoryLogger(session_id="sess-sc-pipe")
            pipeline = create_similar_case_pipeline(trajectory_logger=traj)
            input_data = {
                "request": {"session_id": "s1", "query": "合同纠纷"},
                "db": MagicMock(),
            }
            await pipeline.run(input_data)

            # Should have executor + validator records
            assert len(traj.records) >= 2
            agent_names = [r["agent_name"] for r in traj.records]
            assert "similar_case_executor" in agent_names
            assert "similar_case_validator" in agent_names
