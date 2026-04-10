from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from app.agents.base import RawResult, ValidatedOutput
from app.services.analytics.telemetry import TelemetryService


class GovernanceDecision(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    RETRACT = "retract"


class GovernanceBlockError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        violated_rule: str,
        severity: str = "high",
        rule_pattern_matched: str | None = None,
    ) -> None:
        super().__init__(message)
        self.violated_rule = violated_rule
        self.severity = severity
        self.rule_pattern_matched = rule_pattern_matched


class SchemaValidationError(GovernanceBlockError):
    def __init__(self, violations: list[dict[str, Any]]) -> None:
        super().__init__(
            "output failed schema validation",
            violated_rule="schema.validation_failed",
            severity="high",
        )
        self.violations = violations


class GovernanceAuditLog:
    """Append-only governance audit log with an in-process query cache."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = []
        self._lock = Lock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        decision: GovernanceDecision,
        layer: str,
        rule_name: str | None = None,
        severity: str = "info",
        rules_checked: list[str] | None = None,
        violated_rule: str | None = None,
        rule_pattern_matched: str | None = None,
        message: str | None = None,
        removed_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_id": TelemetryService.instance().get_correlation_id()
            or TelemetryService.instance().set_correlation_id(),
            "decision": decision.value,
            "layer": layer,
            "rule_name": rule_name or violated_rule,
            "severity": severity,
            "rules_checked": list(rules_checked or []),
            "violated_rule": violated_rule,
            "rule_pattern_matched": rule_pattern_matched,
            "message": message,
            "removed_fields": list(removed_fields or []),
        }
        with self._lock:
            self._entries.append(entry)
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        TelemetryService.instance().record_event(
            f"governance.{decision.value}",
            payload=entry,
        )
        return entry

    def query(
        self,
        *,
        decision: GovernanceDecision | str | None = None,
        rule_name: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        decision_value = decision.value if isinstance(decision, GovernanceDecision) else decision
        with self._lock:
            entries = list(self._entries)
        return [
            entry
            for entry in entries
            if (decision_value is None or entry["decision"] == decision_value)
            and (rule_name is None or entry["rule_name"] == rule_name)
            and (severity is None or entry["severity"] == severity)
        ]


class OutputGovernancePipeline:
    DEFAULT_CONTENT_PATTERNS = (
        {
            "name": "pii.phone_number",
            "pattern": r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b",
            "severity": "high",
        },
        {
            "name": "pii.ssn",
            "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
            "severity": "high",
        },
        {
            "name": "harmful.illegal_activity",
            "pattern": r"\b(instructions for illegal activity|build an illegal weapon)\b",
            "severity": "critical",
        },
    )
    DEFAULT_INJECTION_PATTERNS = (
        {
            "name": "prompt_injection.ignore_previous",
            "pattern": r"\bignore\s+(all\s+)?previous\s+instructions\b",
            "severity": "high",
        },
        {
            "name": "prompt_injection.bypass_governance",
            "pattern": r"\b(system\s*:\s*)?bypass\s+governance\b",
            "severity": "critical",
        },
    )
    DEFAULT_CHUNK_PATTERNS = DEFAULT_INJECTION_PATTERNS + (
        {
            "name": "harmful.high_risk_chunk",
            "pattern": r"\bbuild an illegal weapon\b",
            "severity": "critical",
        },
    )
    RULES_CHECKED = ["content_safety", "prompt_injection", "schema"]

    def __init__(
        self,
        *,
        config_path: Path | str | None = None,
        audit_log: GovernanceAuditLog | None = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path is not None else None
        self.audit_log = audit_log or GovernanceAuditLog()
        self._config_mtime_ns: int | None = None
        self._content_patterns = list(self.DEFAULT_CONTENT_PATTERNS)
        self._injection_patterns = list(self.DEFAULT_INJECTION_PATTERNS)
        self._chunk_patterns = list(self.DEFAULT_CHUNK_PATTERNS)

    async def govern_output(self, validated: ValidatedOutput, *, layer: str = "sync") -> ValidatedOutput:
        self._reload_config_if_needed()
        text = self._extract_text(validated.output)
        self._raise_if_matched(text, self._content_patterns)
        self._raise_if_matched(text, self._injection_patterns)
        governed = self._validate_schema(validated, layer=layer)
        self.audit_log.record(
            decision=GovernanceDecision.PASS,
            layer=layer,
            rule_name="governance.pass",
            severity="info",
            rules_checked=self.RULES_CHECKED,
        )
        return governed

    async def govern_raw_result(self, raw_result: RawResult, *, layer: str = "sync") -> None:
        await self.govern_output(
            ValidatedOutput(
                output=raw_result.output,
                schema_name="raw_result",
            ),
            layer=layer,
        )

    async def govern_stream(self, chunks: AsyncIterator[str]) -> AsyncIterator[str]:
        self._reload_config_if_needed()
        emitted: list[str] = []
        async for chunk in chunks:
            violation = self._first_match(chunk, self._chunk_patterns)
            if violation is not None:
                self.audit_log.record(
                    decision=GovernanceDecision.BLOCK,
                    layer="per_chunk",
                    violated_rule=violation["name"],
                    rule_pattern_matched=violation["pattern"],
                    severity=violation.get("severity", "high"),
                )
                yield self.blocked_event(
                    violated_rule=violation["name"],
                    message="stream blocked by output governance",
                )
                return
            emitted.append(chunk)
            yield chunk

        aggregate = "".join(emitted)
        violation = self._first_match(aggregate, self._content_patterns)
        if violation is None:
            violation = self._first_match(aggregate, self._injection_patterns)
        if violation is not None:
            self.audit_log.record(
                decision=GovernanceDecision.RETRACT,
                layer="post_stream",
                violated_rule=violation["name"],
                rule_pattern_matched=violation["pattern"],
                severity=violation.get("severity", "high"),
                message="client must discard prior streamed content",
            )
            yield self.retracted_event(
                violated_rule=violation["name"],
                message="discard prior streamed content",
            )
            return

        self.audit_log.record(
            decision=GovernanceDecision.PASS,
            layer="post_stream",
            rule_name="governance.pass",
            severity="info",
            rules_checked=self.RULES_CHECKED,
        )

    def blocked_event(self, *, violated_rule: str, message: str) -> str:
        return self._event("governance_blocked", violated_rule=violated_rule, message=message)

    def retracted_event(self, *, violated_rule: str, message: str) -> str:
        return self._event("governance_retracted", violated_rule=violated_rule, message=message)

    def _validate_schema(self, validated: ValidatedOutput, *, layer: str) -> ValidatedOutput:
        schema_model = validated.metadata.get("schema_model")
        if schema_model is None:
            return validated

        try:
            parsed = (
                schema_model.model_validate(validated.output)
                if hasattr(schema_model, "model_validate")
                else schema_model.parse_obj(validated.output)
            )
        except Exception as exc:
            violations = self._schema_violations(exc)
            self.audit_log.record(
                decision=GovernanceDecision.BLOCK,
                layer=layer,
                violated_rule="schema.validation_failed",
                severity="high",
                message=json.dumps(violations, ensure_ascii=False, default=str),
            )
            raise SchemaValidationError(violations) from exc

        output = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()
        removed_fields = self._removed_schema_fields(schema_model, validated.output)
        if removed_fields:
            self.audit_log.record(
                decision=GovernanceDecision.PASS,
                layer=layer,
                rule_name="schema.extra_fields_removed",
                severity="info",
                removed_fields=removed_fields,
            )
            return replace(validated, output=output)
        return validated

    def _raise_if_matched(self, text: str, patterns: list[dict[str, str]]) -> None:
        violation = self._first_match(text, patterns)
        if violation is None:
            return
        decision = GovernanceDecision.BLOCK
        self.audit_log.record(
            decision=decision,
            layer="sync",
            violated_rule=violation["name"],
            rule_pattern_matched=violation["pattern"],
            severity=violation.get("severity", "high"),
        )
        raise GovernanceBlockError(
            "output blocked by governance",
            violated_rule=violation["name"],
            severity=violation.get("severity", "high"),
            rule_pattern_matched=violation["pattern"],
        )

    def _first_match(
        self,
        text: str,
        patterns: list[dict[str, str]],
    ) -> dict[str, str] | None:
        normalized = self._normalize(text)
        for rule in patterns:
            if re.search(rule["pattern"], normalized, flags=re.IGNORECASE):
                return rule
        return None

    def _reload_config_if_needed(self) -> None:
        if self.config_path is None or not self.config_path.exists():
            return
        mtime_ns = self.config_path.stat().st_mtime_ns
        if self._config_mtime_ns == mtime_ns:
            return
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        self._content_patterns = list(self.DEFAULT_CONTENT_PATTERNS) + list(
            payload.get("content_patterns", [])
        )
        self._injection_patterns = list(self.DEFAULT_INJECTION_PATTERNS) + list(
            payload.get("injection_patterns", [])
        )
        self._chunk_patterns = list(self.DEFAULT_CHUNK_PATTERNS) + list(
            payload.get("chunk_patterns", [])
        )
        self._config_mtime_ns = mtime_ns

    @staticmethod
    def _extract_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return " ".join(OutputGovernancePipeline._extract_text(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return " ".join(OutputGovernancePipeline._extract_text(item) for item in value)
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _normalize(text: str) -> str:
        return unicodedata.normalize("NFKC", text).casefold()

    @staticmethod
    def _removed_schema_fields(schema_model: Any, output: Any) -> list[str]:
        if not isinstance(output, dict):
            return []
        fields = getattr(schema_model, "model_fields", None) or getattr(schema_model, "__fields__", {})
        return sorted(key for key in output if key not in fields)

    @staticmethod
    def _schema_violations(exc: Exception) -> list[dict[str, Any]]:
        if hasattr(exc, "errors"):
            return list(exc.errors())
        return [{"message": str(exc)}]

    @staticmethod
    def _event(event_type: str, *, violated_rule: str, message: str) -> str:
        return json.dumps(
            {
                "type": event_type,
                "agent_name": "output_governance",
                "payload": {
                    "violated_rule": violated_rule,
                    "message": message,
                },
            },
            ensure_ascii=False,
        ) + "\n"
