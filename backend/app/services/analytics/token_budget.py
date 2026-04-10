from __future__ import annotations

import logging
import math
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import tiktoken

from app.services.analytics.telemetry import TelemetryService

logger = logging.getLogger(__name__)


class TokenBudgetExceededError(ValueError):
    def __init__(
        self,
        *,
        estimated_total: int,
        context_window: int,
        excess_tokens: int,
        truncation_target: int | None = None,
    ) -> None:
        self.estimated_total = estimated_total
        self.context_window = context_window
        self.excess_tokens = excess_tokens
        self.truncation_target = truncation_target
        super().__init__(
            "Token budget exceeded: "
            f"estimated_total={estimated_total}, "
            f"context_window={context_window}, "
            f"excess_tokens={excess_tokens}, "
            f"truncation_target={truncation_target}"
        )


@dataclass(frozen=True, slots=True)
class BudgetAllocation:
    context_window: int
    effective_context_window: int
    segments: dict[str, int]

    @property
    def total_allocated(self) -> int:
        return sum(self.segments.values())


@dataclass(frozen=True, slots=True)
class TokenUsageRecord:
    timestamp: datetime
    correlation_id: str | None
    agent_name: str
    pipeline_type: str
    estimated_tokens: int
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimation_accuracy(self) -> float:
        if self.total_tokens <= 0:
            return 1.0
        return min(self.estimated_tokens, self.total_tokens) / max(
            self.estimated_tokens,
            self.total_tokens,
        )


class TokenBudgetManager:
    def __init__(
        self,
        *,
        safety_margin: float = 0.25,
        cache_size: int = 1024,
        allocation_ratios: dict[str, float] | None = None,
        calibration_threshold: float = 0.15,
        calibration_window: int = 20,
    ) -> None:
        self.safety_margin = safety_margin
        self.cache_size = cache_size
        self.allocation_ratios = allocation_ratios or {
            "system_prompt": 0.20,
            "retrieval_context": 0.50,
            "generation": 0.30,
        }
        self.calibration_threshold = calibration_threshold
        self.calibration_window = calibration_window
        self.calibration_coefficient = 1.0
        self._cache: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_evictions = 0
        self._usage_records: list[TokenUsageRecord] = []
        self._recent_ratios: deque[float] = deque(maxlen=calibration_window)
        self._encodings: dict[str, Any] = {}

    def estimate_tokens(self, text: str, *, model: str = "deepseek-chat") -> int:
        if not text:
            return 0
        cache_key = (model, text)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            self._cache_hits += 1
            return cached

        self._cache_misses += 1
        encoding = self._get_encoding(model)
        estimated = math.ceil(len(encoding.encode(text)) * self.calibration_coefficient)
        self._cache[cache_key] = estimated
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
            self._cache_evictions += 1
        return estimated

    def cache_stats(self) -> dict[str, int]:
        return {
            "entries": len(self._cache),
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "evictions": self._cache_evictions,
        }

    def invalidate_cache(self) -> None:
        self._cache.clear()

    def allocate_budget(
        self,
        *,
        context_window: int,
        fixed_system_prompt_tokens: int | None = None,
    ) -> BudgetAllocation:
        effective_window = self.effective_context_window(context_window)
        ratios = self._normalized_ratios(self.allocation_ratios)
        segments: dict[str, int] = {}

        if fixed_system_prompt_tokens is None:
            for segment, ratio in ratios.items():
                segments[segment] = math.floor(effective_window * ratio)
        else:
            system_tokens = min(fixed_system_prompt_tokens, effective_window)
            remaining = max(effective_window - system_tokens, 0)
            segments["system_prompt"] = system_tokens
            tail_ratios = {
                key: value
                for key, value in ratios.items()
                if key != "system_prompt"
            }
            normalized_tail = self._normalized_ratios(tail_ratios)
            for segment, ratio in normalized_tail.items():
                segments[segment] = math.floor(remaining * ratio)

        return BudgetAllocation(
            context_window=context_window,
            effective_context_window=effective_window,
            segments=segments,
        )

    def enforce_budget(
        self,
        *,
        system_prompt: str = "",
        retrieval_context: str = "",
        user_prompt: str = "",
        generation_tokens: int = 0,
        context_window: int,
        model: str = "deepseek-chat",
    ) -> BudgetAllocation:
        system_tokens = self.estimate_tokens(system_prompt, model=model)
        context_tokens = self.estimate_tokens(retrieval_context, model=model)
        user_tokens = self.estimate_tokens(user_prompt, model=model)
        estimated_total = system_tokens + context_tokens + user_tokens + generation_tokens
        effective_window = self.effective_context_window(context_window)
        if estimated_total > effective_window:
            truncation_target = max(
                effective_window - system_tokens - user_tokens - generation_tokens,
                0,
            )
            raise TokenBudgetExceededError(
                estimated_total=estimated_total,
                context_window=effective_window,
                excess_tokens=estimated_total - effective_window,
                truncation_target=truncation_target,
            )
        return self.allocate_budget(
            context_window=context_window,
            fixed_system_prompt_tokens=system_tokens,
        )

    def estimate_messages(
        self,
        messages: list[dict[str, str]],
        *,
        model: str = "deepseek-chat",
    ) -> int:
        return sum(
            self.estimate_tokens(message.get("content", ""), model=model)
            for message in messages
        )

    def enforce_messages_budget(
        self,
        messages: list[dict[str, str]],
        *,
        generation_tokens: int,
        context_window: int,
        model: str = "deepseek-chat",
    ) -> dict[str, int]:
        prompt_tokens = self.estimate_messages(messages, model=model)
        effective_window = self.effective_context_window(context_window)
        estimated_total = prompt_tokens + generation_tokens
        if estimated_total > effective_window:
            raise TokenBudgetExceededError(
                estimated_total=estimated_total,
                context_window=effective_window,
                excess_tokens=estimated_total - effective_window,
                truncation_target=max(effective_window - generation_tokens, 0),
            )
        return {
            "estimated_prompt_tokens": prompt_tokens,
            "estimated_generation_tokens": generation_tokens,
            "estimated_total": estimated_total,
            "context_window": context_window,
            "effective_context_window": effective_window,
        }

    def record_actual_usage(
        self,
        *,
        estimated_tokens: int,
        prompt_tokens: int,
        completion_tokens: int,
        agent_name: str = "system",
        pipeline_type: str = "default",
        timestamp: datetime | None = None,
        correlation_id: str | None = None,
    ) -> TokenUsageRecord:
        record = TokenUsageRecord(
            timestamp=timestamp or datetime.now(UTC),
            correlation_id=correlation_id
            or TelemetryService.instance().get_correlation_id(),
            agent_name=agent_name,
            pipeline_type=pipeline_type,
            estimated_tokens=estimated_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._usage_records.append(record)
        actual_total = record.total_tokens
        if estimated_tokens > 0 and actual_total > 0:
            ratio = actual_total / estimated_tokens
            self._recent_ratios.append(ratio)
            if ratio > 1 + self.calibration_threshold:
                logger.warning(
                    "Actual token usage exceeded estimate by more than %.0f%%: %.2f",
                    self.calibration_threshold * 100,
                    ratio,
                )
            self._maybe_adjust_calibration()

        TelemetryService.instance().record_token_usage(
            "llm_token_usage",
            prompt=prompt_tokens,
            completion=completion_tokens,
            agent_name=agent_name,
        )
        return record

    def get_usage_stats(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        agent_name: str | None = None,
        pipeline_type: str | None = None,
    ) -> dict[str, float | int]:
        records = [
            record
            for record in self._usage_records
            if (start is None or record.timestamp >= start)
            and (end is None or record.timestamp <= end)
            and (agent_name is None or record.agent_name == agent_name)
            and (pipeline_type is None or record.pipeline_type == pipeline_type)
        ]
        total_tokens = sum(record.total_tokens for record in records)
        request_count = len(records)
        return {
            "request_count": request_count,
            "total_tokens": total_tokens,
            "avg_per_request": total_tokens / request_count if request_count else 0,
            "max_single_request": max(
                (record.total_tokens for record in records),
                default=0,
            ),
            "avg_estimation_accuracy": (
                sum(record.estimation_accuracy for record in records) / request_count
                if request_count
                else 1.0
            ),
        }

    def effective_context_window(self, context_window: int) -> int:
        return math.floor(context_window * (1.0 - self.safety_margin))

    def _get_encoding(self, model: str) -> Any:
        if model not in self._encodings:
            try:
                self._encodings[model] = tiktoken.encoding_for_model(model)
            except KeyError:
                logger.warning(
                    "Tokenizer for model %s was not found; falling back to cl100k_base.",
                    model,
                )
                self._encodings[model] = tiktoken.get_encoding("cl100k_base")
        return self._encodings[model]

    def _maybe_adjust_calibration(self) -> None:
        if len(self._recent_ratios) < self.calibration_window:
            return
        avg_ratio = sum(self._recent_ratios) / len(self._recent_ratios)
        if abs(avg_ratio - self.calibration_coefficient) <= self.calibration_threshold:
            return
        old = self.calibration_coefficient
        self.calibration_coefficient = round(avg_ratio, 4)
        self.invalidate_cache()
        TelemetryService.instance().record_event(
            "token_budget_calibration_adjusted",
            {
                "old_coefficient": old,
                "new_coefficient": self.calibration_coefficient,
                "window_size": len(self._recent_ratios),
            },
            agent_name="token_budget",
        )

    @staticmethod
    def _normalized_ratios(ratios: dict[str, float]) -> dict[str, float]:
        total = sum(max(value, 0.0) for value in ratios.values())
        if total <= 0:
            raise ValueError("allocation ratios must sum to a positive value")
        return {key: max(value, 0.0) / total for key, value in ratios.items()}
