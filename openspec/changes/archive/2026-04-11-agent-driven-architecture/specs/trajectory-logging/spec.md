# Trajectory Logging

## ADDED Requirements

### Requirement: TrajectoryLogger Agent Step Recording

The system SHALL provide a `TrajectoryLogger` that records the full input and output for each agent step in a pipeline execution.

Every invocation of an agent's `run()` method MUST be recorded as a trajectory entry.

#### Scenario: Record planner step input and output

WHEN the PlannerAgent completes execution for a request
THEN the TrajectoryLogger SHALL record: session_id, agent_name="planner", step_type="plan", input summary, output ExecutionPlan, and duration in milliseconds.

#### Scenario: Record executor step input and output

WHEN the ExecutorAgent completes execution for a request
THEN the TrajectoryLogger SHALL record: session_id, agent_name="executor", step_type="execute", input ExecutionPlan, output RawResult, and duration in milliseconds.

#### Scenario: Record validator step input and output

WHEN the ValidatorAgent completes execution for a request
THEN the TrajectoryLogger SHALL record: session_id, agent_name="validator", step_type="validate", input RawResult, output ValidatedOutput or Rejection, and duration in milliseconds.

---

### Requirement: PostgreSQL Storage

Trajectory records SHALL be stored in a PostgreSQL `agent_trajectory` table.

The table schema MUST include: `id` (primary key), `session_id` (indexed), `agent_name`, `step_type`, `input_hash`, `output` (JSONB), `duration_ms`, `token_usage` (JSONB), `created_at`.

#### Scenario: Trajectory record inserted after agent step

WHEN an agent step completes
THEN a row SHALL be inserted into the `agent_trajectory` table
AND the row SHALL contain all required fields populated from the agent execution.

#### Scenario: Query trajectories by session_id

WHEN a query is made for trajectories with a specific session_id
THEN the database SHALL return all trajectory entries for that session ordered by creation time
AND the query SHALL use the index on `session_id` for efficient lookup.

#### Scenario: Input hash is deterministic

WHEN the same input is processed twice
THEN the `input_hash` SHALL be identical for both trajectory records
AND the hash SHALL be computed using SHA-256 on the serialized input JSON.

---

### Requirement: Async Non-Blocking Write

Trajectory recording SHALL NOT block the main pipeline execution.

All database writes for trajectory records MUST be performed asynchronously after the agent step completes.

#### Scenario: Trajectory write does not increase pipeline latency

WHEN an agent step completes and the trajectory is recorded
THEN the next agent step SHALL start immediately without waiting for the trajectory write to complete
AND the trajectory write SHALL occur in a background async task.

#### Scenario: Trajectory write failure does not fail the pipeline

WHEN the trajectory database write fails due to a transient error
THEN the pipeline SHALL continue execution normally
AND the write failure SHALL be logged as a warning without raising an exception to the caller.

---

### Requirement: Trajectory Query API

The system SHALL provide an HTTP endpoint to retrieve trajectory records by session_id.

The endpoint MUST return the full trajectory for a session, ordered by step execution sequence.

#### Scenario: GET trajectories by session_id

WHEN a GET request is made to the trajectory endpoint with a valid session_id
THEN the response SHALL return all trajectory records for that session
AND the records SHALL be ordered chronologically by `created_at`.

#### Scenario: Session not found returns empty list

WHEN a GET request is made with a session_id that has no trajectory records
THEN the endpoint SHALL return an empty list with HTTP 200
AND NOT return a 404 error.

#### Scenario: Response includes all fields

WHEN trajectory records are returned
THEN each record SHALL include: session_id, agent_name, step_type, input_hash, output (parsed JSON), duration_ms, token_usage, created_at.

---

### Requirement: Pipeline Replay from Trajectory

The trajectory records SHALL support full pipeline replay: reconstructing a complete pipeline run from stored trajectory data.

Given a session_id, the system MUST be able to reconstruct the full input/output chain for every agent step.

#### Scenario: Replay reconstructs full pipeline state

WHEN replay is invoked for a session_id
THEN the system SHALL return a replay object containing: the original request, all intermediate step inputs/outputs, and the final result
AND the replay MUST present steps in the same order as the original execution.

#### Scenario: Replay identifies failure point

WHEN the original pipeline execution failed at the executor step
THEN the replay SHALL show the planner step as completed, the executor step as failed, and no validator step
AND the executor step entry SHALL include the error details from the original failure.

#### Scenario: Replay validates output integrity

WHEN replay is invoked
THEN the system SHALL verify that the output of each step matches the input of the next step
AND flag any inconsistencies as replay validation warnings.

---

### Requirement: Prompt Snapshot Capture

Trajectory records SHALL capture the prompt versions used by the pipeline request.

The trajectory store MUST persist enough prompt metadata to reconstruct which prompt templates and versions were used for each step.

#### Scenario: Store prompt version with trajectory step

WHEN an agent step uses one or more prompt templates
THEN the trajectory entry SHALL include the prompt name and resolved version for each template used by that step
AND the prompt metadata SHALL be queryable together with the step record.

#### Scenario: Replay uses original prompt snapshot

WHEN replay is invoked for a historical session
THEN the replay service SHALL present the prompt versions used by the original run
AND missing prompt files in the current filesystem SHALL NOT prevent the replay from identifying the original versions.

---

### Requirement: Trajectory Data Governance

Trajectory storage SHALL apply configurable data governance controls before persisting agent inputs and outputs.

The governance controls MUST support redaction, summary-only storage, explicit full-text opt-in, and retention policies.

#### Scenario: Default trajectory storage redacts sensitive fields

WHEN a trajectory entry contains configured sensitive fields or detected PII
THEN the stored record SHALL redact or hash those fields according to policy
AND the persisted record SHALL remain usable for debugging and replay metadata.

#### Scenario: Full-text storage requires explicit opt-in

WHEN full prompt or response bodies are persisted to the trajectory store
THEN full-text storage SHALL require an explicit configuration flag
AND the persisted records SHALL be marked as full-text for audit and retention handling.

#### Scenario: Retention policy removes expired trajectory data

WHEN trajectory records exceed the configured retention TTL
THEN the system SHALL delete or archive the expired records during a scheduled cleanup cycle
AND the cleanup SHALL be logged with record counts and time range.
