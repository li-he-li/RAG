"""Tests for DSPy production pipeline integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.prompts.optimization import (
    OptimizationResult,
    export_trajectory_evalset,
    create_exact_match_metric,
)


# --- export_trajectory_evalset ---


def test_export_filters_by_prompt_version() -> None:
    """Only records with matching prompt_version are exported."""
    records = [
        {
            "prompt_versions": {"chat": "v1"},
            "input_payload": {"query": "hello"},
            "output": {"answer": "hi"},
        },
        {
            "prompt_versions": {"retrieval": "v1"},
            "input_payload": {"query": "test"},
            "output": {"answer": "result"},
        },
    ]
    # Export for "chat" prompt — should only get first record
    result = export_trajectory_evalset(
        records=records,
        prompt_name="chat",
        input_keys=("query",),
        output_key="answer",
        dspy_module=MagicMock(),
    )
    assert len(result) == 1


def test_export_skips_incomplete_records() -> None:
    """Records missing required fields are skipped."""
    records = [
        {
            "prompt_versions": {"chat": "v1"},
            "input_payload": {"query": "hello"},
            "output": {},  # missing output_key
        },
        {
            "prompt_versions": {"chat": "v1"},
            "input_payload": {},  # missing input_key
            "output": {"answer": "test"},
        },
    ]
    result = export_trajectory_evalset(
        records=records,
        prompt_name="chat",
        input_keys=("query",),
        output_key="answer",
        dspy_module=MagicMock(),
    )
    assert len(result) == 0


def test_export_empty_records_returns_empty() -> None:
    result = export_trajectory_evalset(
        records=[],
        prompt_name="chat",
        input_keys=("query",),
        output_key="answer",
        dspy_module=MagicMock(),
    )
    assert result == []


# --- create_exact_match_metric ---


def test_exact_match_metric_returns_true() -> None:
    metric = create_exact_match_metric("answer")
    example = MagicMock()
    example.answer = "yes"
    prediction = MagicMock()
    prediction.answer = "yes"
    assert metric(example, prediction) is True


def test_exact_match_metric_returns_false() -> None:
    metric = create_exact_match_metric("answer")
    example = MagicMock()
    example.answer = "yes"
    prediction = MagicMock()
    prediction.answer = "no"
    assert metric(example, prediction) is False


# --- OptimizationResult ---


def test_optimization_result_fields() -> None:
    result = OptimizationResult(
        compiled_program=MagicMock(),
        validation_score=0.85,
        compiled=True,
    )
    assert result.validation_score == 0.85
    assert result.compiled is True
