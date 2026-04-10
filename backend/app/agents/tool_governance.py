from __future__ import annotations

import inspect
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from app.services.analytics.telemetry import TelemetryService


class ToolSideEffectLevel(StrEnum):
    READ_ONLY = "read_only"
    STATEFUL = "stateful"
    EXTERNAL = "external"


class ToolDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    APPROVAL_REQUIRED = "approval-required"


class ToolInvocationBlocked(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.metadata = dict(metadata or {})


class ToolApprovalRequired(ToolInvocationBlocked):
    def __init__(self, *, tool_name: str, agent_name: str) -> None:
        super().__init__(
            "tool invocation requires external approval",
            reason="approval_required",
            metadata={"tool_name": tool_name, "agent_name": agent_name},
        )


@dataclass(frozen=True, slots=True)
class GovernedTool:
    name: str
    func: Callable[..., Any]
    args_schema: type
    side_effect_level: ToolSideEffectLevel


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    agent_name: str
    tool_name: str
    raw_arguments: dict[str, Any]
    normalized_parameters: dict[str, Any]
    side_effect_level: ToolSideEffectLevel


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, GovernedTool] = {}

    def register(
        self,
        *,
        name: str,
        func: Callable[..., Any],
        args_schema: type,
        side_effect_level: ToolSideEffectLevel,
    ) -> None:
        if not name:
            raise ValueError("tool name is required")
        self._tools[name] = GovernedTool(
            name=name,
            func=func,
            args_schema=args_schema,
            side_effect_level=side_effect_level,
        )

    def discover(self, name: str) -> GovernedTool | None:
        return self._tools.get(name)


class ToolAuditLog:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = []
        self._lock = Lock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        decision: ToolDecision,
        agent_name: str,
        tool_name: str,
        reason: str | None = None,
        normalized_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_id": TelemetryService.instance().get_correlation_id()
            or TelemetryService.instance().set_correlation_id(),
            "agent_name": agent_name,
            "tool_name": tool_name,
            "decision": decision.value,
            "reason": reason,
            "normalized_parameters": dict(normalized_parameters or {}),
            "parameter_summary": self._summarize_parameters(normalized_parameters or {}),
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            self._entries.append(entry)
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        TelemetryService.instance().record_event(
            f"tool_governance.{decision.value}",
            payload=entry,
        )
        return entry

    def query(
        self,
        *,
        decision: ToolDecision | str | None = None,
        tool_name: str | None = None,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        decision_value = decision.value if isinstance(decision, ToolDecision) else decision
        with self._lock:
            entries = list(self._entries)
        return [
            entry
            for entry in entries
            if (decision_value is None or entry["decision"] == decision_value)
            and (tool_name is None or entry["tool_name"] == tool_name)
            and (reason is None or entry["reason"] == reason)
        ]

    @staticmethod
    def _summarize_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            key: ("<redacted>" if "secret" in key.lower() or "password" in key.lower() else value)
            for key, value in parameters.items()
        }


class ToolGovernancePolicy:
    INJECTION_PATTERNS = (
        r"\bignore\s+governance\b",
        r"\bbypass\s+tool\s+policy\b",
        r"\bignore\s+(all\s+)?previous\s+instructions\b",
        r"\bdisable\s+tool\s+governance\b",
    )

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        audit_log: ToolAuditLog | None = None,
        approval_policy: Callable[[ToolInvocation], bool] | None = None,
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.audit_log = audit_log or ToolAuditLog()
        self.approval_policy = approval_policy

    async def invoke(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        tool = self.registry.discover(tool_name)
        if tool is None:
            self._block(
                agent_name=agent_name,
                tool_name=tool_name,
                reason="tool_not_allowed",
                metadata={"arguments": dict(arguments)},
            )

        normalized = self._validate_arguments(tool, arguments, agent_name=agent_name)
        invocation = ToolInvocation(
            agent_name=agent_name,
            tool_name=tool_name,
            raw_arguments=dict(arguments),
            normalized_parameters=normalized,
            side_effect_level=tool.side_effect_level,
        )
        self._detect_injection(invocation)
        self._enforce_side_effect_policy(invocation)

        self.audit_log.record(
            decision=ToolDecision.ALLOW,
            agent_name=agent_name,
            tool_name=tool_name,
            normalized_parameters=normalized,
        )
        result = tool.func(**normalized)
        if inspect.isawaitable(result):
            return await result
        return result

    def _validate_arguments(
        self,
        tool: GovernedTool,
        arguments: dict[str, Any],
        *,
        agent_name: str,
    ) -> dict[str, Any]:
        try:
            parsed = (
                tool.args_schema.model_validate(arguments)
                if hasattr(tool.args_schema, "model_validate")
                else tool.args_schema.parse_obj(arguments)
            )
        except Exception as exc:
            errors = exc.errors() if hasattr(exc, "errors") else [{"message": str(exc)}]
            self._block(
                agent_name=agent_name,
                tool_name=tool.name,
                reason="schema_validation_failed",
                metadata={"validation_errors": errors},
            )
        return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()

    def _detect_injection(self, invocation: ToolInvocation) -> None:
        text = self._extract_text(invocation.normalized_parameters)
        normalized = unicodedata.normalize("NFKC", text).casefold()
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in self.INJECTION_PATTERNS):
            self._block(
                agent_name=invocation.agent_name,
                tool_name=invocation.tool_name,
                reason="tool_input_injection_detected",
                normalized_parameters=invocation.normalized_parameters,
            )

    def _enforce_side_effect_policy(self, invocation: ToolInvocation) -> None:
        if invocation.side_effect_level == ToolSideEffectLevel.READ_ONLY:
            return
        if self.approval_policy is not None and self.approval_policy(invocation):
            return
        self.audit_log.record(
            decision=ToolDecision.APPROVAL_REQUIRED,
            agent_name=invocation.agent_name,
            tool_name=invocation.tool_name,
            reason="approval_required",
            normalized_parameters=invocation.normalized_parameters,
            metadata={"side_effect_level": invocation.side_effect_level.value},
        )
        raise ToolApprovalRequired(
            tool_name=invocation.tool_name,
            agent_name=invocation.agent_name,
        )

    def _block(
        self,
        *,
        agent_name: str,
        tool_name: str,
        reason: str,
        normalized_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        metadata = dict(metadata or {})
        self.audit_log.record(
            decision=ToolDecision.BLOCK,
            agent_name=agent_name,
            tool_name=tool_name,
            reason=reason,
            normalized_parameters=normalized_parameters,
            metadata=metadata,
        )
        raise ToolInvocationBlocked(
            "tool invocation blocked by governance",
            reason=reason,
            metadata=metadata,
        )

    @staticmethod
    def _extract_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return " ".join(ToolGovernancePolicy._extract_text(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return " ".join(ToolGovernancePolicy._extract_text(item) for item in value)
        return json.dumps(value, ensure_ascii=False, default=str)
