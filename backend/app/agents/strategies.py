"""
Planning strategies for dynamic ExecutionPlan generation.

Instead of hardcoded single-step plans, each PlannerAgent selects a strategy
based on input complexity, producing plans with varying numbers of steps.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from app.agents.base import ExecutionPlan, PlanStep


class InputComplexity(Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


def classify_complexity(input_data: dict[str, Any]) -> InputComplexity:
    """Classify input complexity based on attachments, query length, and dispute tags.

    Rules:
    - SIMPLE: no attachments, short query, no dispute tags
    - MEDIUM: 1 attachment or medium query
    - COMPLEX: 2+ attachments or dispute_tags present or long query
    """
    attachments = input_data.get("attachments", [])
    query = str(input_data.get("query", ""))
    dispute_tags = input_data.get("dispute_tags")

    n_attachments = len(attachments) if isinstance(attachments, list | tuple) else 0
    has_dispute_tags = bool(dispute_tags)

    if n_attachments >= 2 or has_dispute_tags or len(query) > 50:
        return InputComplexity.COMPLEX
    if n_attachments == 1 or len(query) > 15:
        return InputComplexity.MEDIUM
    return InputComplexity.SIMPLE


class PlanningStrategy(ABC):
    """Abstract base for planning strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this strategy."""

    @abstractmethod
    def should_apply(self, complexity: InputComplexity) -> bool:
        """Whether this strategy should be used for the given complexity."""

    @abstractmethod
    async def build_plan(self, input_data: dict[str, Any]) -> ExecutionPlan:
        """Build an ExecutionPlan for the given input."""


class StrategyRegistry:
    """Registry of planning strategies, selected by input complexity."""

    def __init__(self) -> None:
        self._strategies: list[PlanningStrategy] = []

    def register(self, strategy: PlanningStrategy) -> None:
        self._strategies.append(strategy)

    def select(self, complexity: InputComplexity) -> PlanningStrategy | None:
        """Return the first strategy that should_apply for the given complexity."""
        for strategy in self._strategies:
            if strategy.should_apply(complexity):
                return strategy
        return None

    def list_strategies(self) -> list[str]:
        return [s.name for s in self._strategies]
