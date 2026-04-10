from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.analytics.middleware import CorrelationIdMiddleware
from app.services.analytics.telemetry import TelemetryService


def test_telemetry_singleton_records_structured_json_events() -> None:
    telemetry = TelemetryService.instance()
    telemetry.reset()

    with telemetry.correlation_context("corr-test-1"):
        event = telemetry.record_event(
            "plan_created",
            {"agent": "planner", "steps": 3},
            agent_name="planner",
        )

    assert TelemetryService.instance() is telemetry
    assert event["correlation_id"] == "corr-test-1"
    assert event["agent_name"] == "planner"
    assert event["event_type"] == "plan_created"
    assert event["payload"] == {"agent": "planner", "steps": 3}
    assert json.loads(telemetry.serialize_event(event)) == event
    assert telemetry.events[-1] == event


def test_telemetry_collects_latency_tokens_and_outcomes() -> None:
    telemetry = TelemetryService.instance()
    telemetry.reset()

    telemetry.record_latency("executor_run", 100, agent_name="executor")
    telemetry.record_latency("executor_run", 400, agent_name="executor")
    telemetry.record_latency("executor_run", 900, agent_name="executor")
    telemetry.record_token_usage(
        "executor_llm_call",
        prompt=1200,
        completion=350,
        agent_name="executor",
    )
    telemetry.record_outcome("pipeline", "success", agent_name="executor")
    telemetry.record_outcome("pipeline", "failure", agent_name="executor")

    histogram = telemetry.get_latency_histogram("executor_run")
    token_usage = telemetry.get_token_usage(agent_name="executor")
    outcomes = telemetry.get_outcomes("pipeline")

    assert histogram["count"] == 3
    assert histogram["p50"] == 400
    assert histogram["p95"] == 900
    assert histogram["p99"] == 900
    assert token_usage["prompt"] == 1200
    assert token_usage["completion"] == 350
    assert token_usage["total"] == 1550
    assert outcomes["success"] == 1
    assert outcomes["failure"] == 1
    assert outcomes["success_rate"] == 0.5


def test_correlation_id_middleware_injects_and_propagates_id() -> None:
    telemetry = TelemetryService.instance()
    telemetry.reset()
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str | None]:
        telemetry.record_event("handler_seen")
        return {"correlation_id": telemetry.get_correlation_id()}

    client = TestClient(app)
    response = client.get("/ping", headers={"x-correlation-id": "client-corr-1"})

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "client-corr-1"
    assert response.json() == {"correlation_id": "client-corr-1"}
    assert telemetry.events[-1]["correlation_id"] == "client-corr-1"


def test_correlation_id_middleware_generates_missing_id() -> None:
    telemetry = TelemetryService.instance()
    telemetry.reset()
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str | None]:
        return {"correlation_id": telemetry.get_correlation_id()}

    response = TestClient(app).get("/ping")

    assert response.status_code == 200
    generated = response.headers["x-correlation-id"]
    assert generated
    assert response.json() == {"correlation_id": generated}
