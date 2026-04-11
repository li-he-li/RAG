# Telemetry Service

## ADDED Requirements

### Requirement: TelemetryService Singleton

The system SHALL provide a `TelemetryService` singleton that serves as the centralized point for all event, metric, and span recording.

All services and agents SHALL use the TelemetryService instance for observability instead of direct logger calls.

#### Scenario: Singleton instance is accessible globally

WHEN `TelemetryService.instance()` is called from any module
THEN it SHALL return the same singleton instance
AND multiple calls from different modules SHALL return identical objects.

#### Scenario: TelemetryService replaces direct logger calls

WHEN a service currently uses `logger.info("Request processed")`
THEN it SHALL be replaced with `TelemetryService.instance().record_event("request_processed", {...})`
AND the telemetry event SHALL contain at minimum: timestamp, event_type, and contextual data.

---

### Requirement: Structured Events

The TelemetryService SHALL record structured events in JSON format.

Every event MUST include: `timestamp` (ISO 8601), `correlation_id` (string), `agent_name` (string), `event_type` (string), and an optional `payload` (JSON object).

#### Scenario: Event with all required fields

WHEN `TelemetryService.record_event("plan_created", {"agent": "planner", "steps": 3})` is called
THEN an event SHALL be recorded with: timestamp, correlation_id, agent_name="planner", event_type="plan_created", payload containing steps count.

#### Scenario: Event without optional payload

WHEN `TelemetryService.record_event("pipeline_started")` is called without a payload
THEN the event SHALL be recorded with all required fields and an empty payload object.

#### Scenario: Events are valid JSON

WHEN events are serialized for storage or transmission
THEN each event SHALL be a valid JSON object
AND the JSON SHALL be parseable by standard JSON tools without errors.

---

### Requirement: Metrics Collection

The TelemetryService SHALL collect and expose metrics for latency histograms, token usage counters, and success/failure rates.

Metrics MUST be aggregatable over time windows.

#### Scenario: Record latency histogram

WHEN an agent step completes in 450ms
THEN `TelemetryService.record_latency("executor_run", 450)` SHALL add the value to the executor_run latency histogram
AND the histogram SHALL support queries for p50, p95, and p99 percentiles.

#### Scenario: Record token usage counter

WHEN an LLM call uses 1200 prompt tokens and 350 completion tokens
THEN `TelemetryService.record_token_usage("executor_llm_call", prompt=1200, completion=350)` SHALL increment the counters
AND the counters SHALL be queryable by agent name and time window.

#### Scenario: Record success and failure rates

WHEN a pipeline execution completes successfully
THEN `TelemetryService.record_outcome("pipeline", "success")` SHALL increment the success counter
AND `record_outcome("pipeline", "failure")` SHALL increment the failure counter
AND the service SHALL compute a success rate as success / (success + failure).

---

### Requirement: Correlation ID Propagation

The TelemetryService SHALL assign a unique correlation ID to each request and propagate it through the entire agent pipeline.

Every event, metric, and log entry within a single request flow MUST share the same correlation ID.

#### Scenario: Correlation ID assigned on request start

WHEN a new HTTP request enters the pipeline
THEN the TelemetryService SHALL generate a unique correlation ID (UUID v4)
AND store it in a context variable accessible to all agents in the pipeline.

#### Scenario: Correlation ID propagated to all agents

WHEN the PlannerAgent, ExecutorAgent, and ValidatorAgent execute within a single request
THEN all events emitted by these agents SHALL share the same correlation ID
AND the correlation ID SHALL be included in every telemetry event and log entry.

#### Scenario: Correlation ID unique across requests

WHEN two concurrent requests are processed
THEN each SHALL have a distinct correlation ID
AND no event from one request SHALL share a correlation ID with the other.

---

### Requirement: Drop-In Logger Replacement

The TelemetryService SHALL serve as a drop-in replacement for direct `logger` calls in existing services.

The migration path MUST be straightforward: replace `logger.info/warning/error` with corresponding TelemetryService methods.

#### Scenario: Replace logger.info with telemetry event

WHEN a service call `logger.info("Search completed", extra={"query": q})` is migrated
THEN it SHALL be replaced with `telemetry.record_event("search_completed", {"query": q})`
AND the telemetry infrastructure SHALL handle formatting and output.

#### Scenario: Backward compatibility with logging

WHEN the TelemetryService records an event
THEN it SHALL also emit a standard Python log entry at the appropriate level
AND existing log aggregation tools SHALL continue to work unchanged.

---

### Requirement: Async Batched Write

The TelemetryService SHALL write events and metrics asynchronously in batches to avoid blocking the main request pipeline.

Telemetry recording calls MUST return immediately without waiting for I/O completion.

#### Scenario: Events are buffered and flushed asynchronously

WHEN `record_event()` is called during request processing
THEN the event SHALL be added to an in-memory buffer and the method SHALL return immediately
AND the buffer SHALL be flushed to the backing store in background batches.

#### Scenario: Batch flush interval is configurable

WHEN the flush interval is set to 5 seconds
THEN the telemetry service SHALL flush accumulated events every 5 seconds
AND the interval SHALL be changeable via configuration without code changes.

#### Scenario: Buffer overflow handled gracefully

WHEN the event buffer exceeds its configured maximum size
THEN the telemetry service SHALL flush immediately regardless of the timer
AND no events SHALL be dropped due to buffer overflow.
