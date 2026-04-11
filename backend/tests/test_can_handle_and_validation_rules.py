"""Tests for AgentBase.can_handle() and ValidationRule protocol."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from app.agents.base import (
    AgentBase,
    ExecutorAgent,
    PlannerAgent,
    RawResult,
    Rejection,
    ValidatedOutput,
    ValidationFail,
    ValidationPass,
    ValidationRule,
    ValidatorAgent,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- can_handle tests ---


class StubAgent(ExecutorAgent[dict[str, Any], RawResult]):
    """Agent that claims to handle requests with 'query' key."""

    @property
    def name(self) -> str:
        return "stub_agent"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        return RawResult(status="success", output={})

    async def can_handle(self, input_data: Any) -> float:
        if isinstance(input_data, dict) and "query" in input_data:
            return 0.9
        return 0.0


class AlwaysConfidentAgent(ExecutorAgent[dict[str, Any], RawResult]):
    """Agent that always returns 1.0 confidence."""

    @property
    def name(self) -> str:
        return "always_confident"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, input_data: dict[str, Any]) -> RawResult:
        return RawResult(status="success", output={})


def test_can_handle_default_returns_zero() -> None:
    """Default AgentBase.can_handle() returns 0.0."""
    agent = AlwaysConfidentAgent()
    score = _run(agent.can_handle({"anything": True}))
    assert score == 0.0


def test_can_handle_custom_returns_confidence() -> None:
    """Overridden can_handle() returns the correct score."""
    agent = StubAgent()
    assert _run(agent.can_handle({"query": "hello"})) == 0.9
    assert _run(agent.can_handle({"other": "data"})) == 0.0


def test_can_handle_score_between_zero_and_one() -> None:
    """can_handle() must return a float in [0.0, 1.0]."""
    agent = StubAgent()
    for payload in [{}, {"query": "test"}, {"other": 1}]:
        score = _run(agent.can_handle(payload))
        assert 0.0 <= score <= 1.0


def test_can_handle_threshold_semantics() -> None:
    """Score >= 0.5 means the agent is a candidate."""
    agent = StubAgent()
    assert _run(agent.can_handle({"query": "x"})) >= 0.5  # candidate
    assert _run(agent.can_handle({"no_query": True})) < 0.5  # not a candidate


# --- ValidationRule tests ---


class SchemaValidationRule(ValidationRule):
    """Checks that output has required keys."""

    def __init__(self, required_keys: tuple[str, ...]) -> None:
        self.required_keys = required_keys
        self.retryable = True

    def check(self, output: Any) -> ValidationPass | ValidationFail:
        if not isinstance(output, dict):
            return ValidationFail(reason="output is not a dict", retryable=self.retryable)
        missing = [k for k in self.required_keys if k not in output]
        if missing:
            return ValidationFail(
                reason=f"missing keys: {missing}",
                retryable=self.retryable,
            )
        return ValidationPass()


class AlwaysFailRule(ValidationRule):
    """Always fails with non-retryable reason."""

    def check(self, output: Any) -> ValidationFail:
        return ValidationFail(reason="permission denied", retryable=False)


def test_validation_pass_is_truthy() -> None:
    result = ValidationPass()
    assert bool(result) is True
    assert result.passed is True


def test_validation_fail_is_falsy() -> None:
    result = ValidationFail(reason="bad output", retryable=True)
    assert bool(result) is False
    assert result.passed is False
    assert result.reason == "bad output"
    assert result.retryable is True


def test_validation_fail_non_retryable() -> None:
    result = ValidationFail(reason="permission denied", retryable=False)
    assert result.retryable is False


def test_schema_rule_passes_on_valid_output() -> None:
    rule = SchemaValidationRule(required_keys=("answer", "citations"))
    result = rule.check({"answer": "yes", "citations": []})
    assert isinstance(result, ValidationPass)


def test_schema_rule_fails_on_missing_keys() -> None:
    rule = SchemaValidationRule(required_keys=("answer", "citations"))
    result = rule.check({"answer": "yes"})
    assert isinstance(result, ValidationFail)
    assert "citations" in result.reason
    assert result.retryable is True


def test_schema_rule_fails_on_non_dict() -> None:
    rule = SchemaValidationRule(required_keys=("answer",))
    result = rule.check("not a dict")
    assert isinstance(result, ValidationFail)


# --- ValidatorAgent with ValidationRule chain ---


class RuleBasedValidator(ValidatorAgent[RawResult, ValidatedOutput | Rejection]):
    """Validator that applies a chain of ValidationRule instances."""

    def __init__(self, rules: list[ValidationRule]) -> None:
        self._rules = rules

    @property
    def name(self) -> str:
        return "rule_based_validator"

    async def validate(self, input_data: Any) -> None:
        pass

    async def run(self, raw_result: RawResult) -> ValidatedOutput | Rejection:
        if raw_result.status == "error":
            return ValidatedOutput(
                output=raw_result.output,
                schema_name="RawResult",
                metadata={"error": raw_result.error},
            )

        for rule in self._rules:
            result = rule.check(raw_result.output)
            if isinstance(result, ValidationFail):
                return Rejection(
                    reasons=(result.reason,),
                    details={"retryable": result.retryable},
                )

        return ValidatedOutput(output=raw_result.output, schema_name="Validated")


def test_rule_based_validator_passes() -> None:
    validator = RuleBasedValidator(rules=[SchemaValidationRule(("answer",))])
    raw = RawResult(status="success", output={"answer": "test"})
    result = _run(validator.run(raw))
    assert isinstance(result, ValidatedOutput)
    assert result.output["answer"] == "test"


def test_rule_based_validator_rejects() -> None:
    validator = RuleBasedValidator(rules=[SchemaValidationRule(("answer", "citations"))])
    raw = RawResult(status="success", output={"answer": "test"})
    result = _run(validator.run(raw))
    assert isinstance(result, Rejection)
    assert any("citations" in r for r in result.reasons)


def test_rule_based_validator_first_failure_stops_chain() -> None:
    """First failing rule produces rejection; subsequent rules do not run."""
    call_count = 0

    class CountingRule(ValidationRule):
        def check(self, output: Any) -> ValidationPass | ValidationFail:
            nonlocal call_count
            call_count += 1
            return ValidationFail(reason="fail early", retryable=True)

    validator = RuleBasedValidator(rules=[CountingRule(), CountingRule()])
    raw = RawResult(status="success", output={})
    result = _run(validator.run(raw))
    assert isinstance(result, Rejection)
    assert call_count == 1  # second rule never ran


def test_rule_based_validator_error_result_passes_through() -> None:
    validator = RuleBasedValidator(rules=[SchemaValidationRule(("answer",))])
    raw = RawResult(status="error", output=None, error="db error")
    result = _run(validator.run(raw))
    assert isinstance(result, ValidatedOutput)
    assert result.metadata.get("error") == "db error"


def test_non_retryable_rejection_flagged() -> None:
    validator = RuleBasedValidator(rules=[AlwaysFailRule()])
    raw = RawResult(status="success", output={})
    result = _run(validator.run(raw))
    assert isinstance(result, Rejection)
    assert result.details.get("retryable") is False
