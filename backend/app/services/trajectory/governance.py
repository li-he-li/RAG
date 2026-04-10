"""
Trajectory data governance: redaction, full-text control, TTL.
"""
from __future__ import annotations

import re
from typing import Any


class RedactionRule:
    """Replace field values matching a pattern with a mask."""

    def __init__(self, field_pattern: str, replacement: str = "[REDACTED]") -> None:
        self._pattern = re.compile(field_pattern, re.IGNORECASE)
        self._replacement = replacement

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        result = dict(data)
        for key in result:
            if self._pattern.search(key):
                result[key] = self._replacement
        return result


# Default sensitive field patterns
_DEFAULT_REDACTION_RULES = [
    RedactionRule(r"phone|tel|mobile"),
    RedactionRule(r"email|mail"),
    RedactionRule(r"id_number|id_card|passport|ssn"),
    RedactionRule(r"password|secret|token|api_key"),
    RedactionRule(r"address|addr"),
    RedactionRule(r"birth|birthday|dob"),
    RedactionRule(r"bank|credit|debit"),
]


class DataGovernancePolicy:
    """Applies redaction and retention rules to trajectory data."""

    def __init__(
        self,
        *,
        redaction_rules: list[RedactionRule] | None = None,
        full_text_enabled: bool = False,
        max_output_length: int = 500,
    ) -> None:
        self._rules = redaction_rules or _DEFAULT_REDACTION_RULES
        self._full_text_enabled = full_text_enabled
        self._max_output_length = max_output_length

    @property
    def full_text_enabled(self) -> bool:
        return self._full_text_enabled

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        for rule in self._rules:
            result = rule.apply(result)
        # Truncate long text fields if not full-text mode
        if not self._full_text_enabled:
            for key, value in result.items():
                if isinstance(value, str) and len(value) > self._max_output_length:
                    result[key] = value[: self._max_output_length] + "...[TRUNCATED]"
        return result


def default_governance_policy() -> DataGovernancePolicy:
    """Return the default governance policy with standard redaction rules."""
    return DataGovernancePolicy(
        redaction_rules=_DEFAULT_REDACTION_RULES,
        full_text_enabled=False,
    )
