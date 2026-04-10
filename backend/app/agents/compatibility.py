from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from app.agents.base import RawResult, Rejection, ValidatedOutput
from app.agents.output_governance import GovernanceBlockError, SchemaValidationError


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    status_code: int
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EndpointContract:
    name: str
    response_mapper: Callable[[Any], dict[str, Any]]
    public_stream_event_types: frozenset[str]
    error_event_detail: str = "Internal server error."


class CompatibilityAdapter:
    INTERNAL_EVENT_TYPES = frozenset(
        {
            "step_started",
            "step_completed",
            "plan_created",
            "validation_passed",
            "pipeline_completed",
        }
    )

    def __init__(self, contract: EndpointContract) -> None:
        self.contract = contract

    def adapt_response(self, result: RawResult | ValidatedOutput | dict[str, Any]) -> dict[str, Any]:
        if isinstance(result, ValidatedOutput):
            return self.contract.response_mapper(result.output)
        if isinstance(result, RawResult):
            return self.contract.response_mapper(result.output)
        return self.contract.response_mapper(result)

    async def adapt_stream(self, events: AsyncIterator[str]) -> AsyncIterator[str]:
        async for line in events:
            if not line.strip():
                continue
            event = json.loads(line)
            event_type = event.get("type")

            if event_type in self.contract.public_stream_event_types:
                yield self._encode(event)
                continue

            if event_type in self.INTERNAL_EVENT_TYPES:
                continue

            mapped = self._map_internal_stream_event(event)
            if mapped is not None:
                yield self._encode(mapped)

    def adapt_error(self, error: BaseException | Rejection) -> ErrorEnvelope:
        if isinstance(error, Rejection):
            return self._error(
                status_code=422,
                error="validation_rejected",
                detail="Agent validation rejected the response.",
            )
        if isinstance(error, (GovernanceBlockError, SchemaValidationError)):
            return self._error(
                status_code=403,
                error="governance_blocked",
                detail="Response was blocked by governance.",
            )
        if isinstance(error, TimeoutError):
            return self._error(
                status_code=504,
                error="timeout",
                detail="Request timed out.",
            )
        return self._error(
            status_code=500,
            error="internal_error",
            detail=self.contract.error_event_detail,
        )

    def _map_internal_stream_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = event.get("type")
        if event_type in {"governance_blocked", "governance_retracted"}:
            return {
                "type": "error",
                "detail": "Response was blocked by governance.",
            }
        if event_type == "validation_rejected":
            return {
                "type": "error",
                "detail": "Agent validation rejected the response.",
            }
        return None

    @staticmethod
    def _error(*, status_code: int, error: str, detail: str) -> ErrorEnvelope:
        return ErrorEnvelope(
            status_code=status_code,
            payload={
                "error": error,
                "detail": detail,
                "citation_missing": False,
            },
        )

    @staticmethod
    def _encode(event: dict[str, Any]) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"
