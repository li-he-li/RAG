from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.prompts.registry import PromptRegistry
from app.services.analytics.token_budget import (
    TokenBudgetExceededError,
    TokenBudgetManager,
)


def test_estimate_tokens_uses_cache_and_handles_empty_text() -> None:
    manager = TokenBudgetManager(cache_size=8)

    assert manager.estimate_tokens("") == 0
    first = manager.estimate_tokens("Analyze this contract clause")
    second = manager.estimate_tokens("Analyze this contract clause")

    assert first > 0
    assert second == first
    assert manager.cache_stats()["hits"] == 1
    assert manager.cache_stats()["misses"] == 1


def test_lru_cache_eviction_and_content_change_recompute() -> None:
    manager = TokenBudgetManager(cache_size=2)

    old_count = manager.estimate_tokens("static prompt")
    manager.estimate_tokens("other prompt")
    manager.estimate_tokens("third prompt")
    changed_count = manager.estimate_tokens("static prompt changed")
    manager.estimate_tokens("static prompt")

    assert changed_count != old_count or changed_count > 0
    assert manager.cache_stats()["evictions"] >= 2


def test_budget_allocation_uses_25_percent_safety_margin() -> None:
    manager = TokenBudgetManager()

    allocation = manager.allocate_budget(context_window=8000)

    assert allocation.context_window == 8000
    assert allocation.effective_context_window == 6000
    assert allocation.total_allocated <= allocation.effective_context_window
    assert set(allocation.segments) == {
        "system_prompt",
        "retrieval_context",
        "generation",
    }


def test_custom_budget_allocation_subtracts_fixed_system_prompt() -> None:
    manager = TokenBudgetManager(
        allocation_ratios={
            "system_prompt": 0.10,
            "retrieval_context": 0.50,
            "generation": 0.40,
        }
    )

    allocation = manager.allocate_budget(
        context_window=1000,
        fixed_system_prompt_tokens=100,
    )

    assert allocation.segments["system_prompt"] == 100
    assert allocation.effective_context_window == 750
    assert allocation.total_allocated <= 750
    assert allocation.segments["retrieval_context"] == 361
    assert allocation.segments["generation"] == 288


def test_enforce_budget_rejects_overflow_with_truncation_target() -> None:
    manager = TokenBudgetManager(safety_margin=0.25)
    long_context = "证据 " * 2000

    with pytest.raises(TokenBudgetExceededError) as error:
        manager.enforce_budget(
            system_prompt="system",
            retrieval_context=long_context,
            generation_tokens=100,
            context_window=256,
        )

    assert error.value.estimated_total > error.value.context_window
    assert error.value.excess_tokens > 0
    assert error.value.truncation_target is not None
    assert error.value.truncation_target >= 0


def test_actual_usage_tracking_and_adaptive_calibration() -> None:
    manager = TokenBudgetManager()
    old_coefficient = manager.calibration_coefficient
    now = datetime.now(UTC)

    for index in range(20):
        manager.record_actual_usage(
            estimated_tokens=100,
            prompt_tokens=150,
            completion_tokens=10,
            agent_name="executor",
            pipeline_type="chat",
            timestamp=now + timedelta(seconds=index),
            correlation_id=f"corr-{index}",
        )

    stats = manager.get_usage_stats(
        start=now - timedelta(seconds=1),
        end=now + timedelta(seconds=30),
        agent_name="executor",
    )

    assert manager.calibration_coefficient > old_coefficient
    assert stats["request_count"] == 20
    assert stats["total_tokens"] == 3200
    assert stats["max_single_request"] == 160
    assert stats["avg_per_request"] == 160
    assert stats["avg_estimation_accuracy"] > 0


def test_prompt_registry_render_with_budget_allows_and_rejects() -> None:
    manager = TokenBudgetManager()
    registry = PromptRegistry("app/prompts")

    rendered = registry.render_with_budget(
        "retrieval_explanation",
        {
            "query": "合同解除",
            "file_name": "case.pdf",
            "line_start": 1,
            "line_end": 2,
            "snippet": "双方约定解除条件。",
        },
        token_budget_manager=manager,
        context_window=8000,
        generation_tokens=200,
    )

    assert rendered.token_budget is not None
    assert rendered.token_budget["estimated_total"] > 0

    with pytest.raises(TokenBudgetExceededError):
        registry.render_with_budget(
            "retrieval_explanation",
            {
                "query": "合同解除",
                "file_name": "case.pdf",
                "line_start": 1,
                "line_end": 2,
                "snippet": "证据 " * 2000,
            },
            token_budget_manager=manager,
            context_window=256,
            generation_tokens=200,
        )
