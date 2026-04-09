# Checkpoint Resume

## ADDED Requirements

### Requirement: CheckpointManager State Serialization

The system SHALL provide a `CheckpointManager` that serializes pipeline state after each agent step completes.

The serialized state MUST capture all information needed to resume the pipeline from that point.

#### Scenario: Checkpoint saved after planner step

WHEN the PlannerAgent completes and returns an ExecutionPlan
THEN the CheckpointManager SHALL serialize the plan along with the original request context
AND store the checkpoint keyed by session_id with step index set to 0 (planner complete).

#### Scenario: Checkpoint saved after executor step

WHEN the ExecutorAgent completes and returns a RawResult
THEN the CheckpointManager SHALL serialize the result along with the execution plan and request context
AND store the checkpoint with step index set to 1 (executor complete).

#### Scenario: Checkpoint saved after validator step

WHEN the ValidatorAgent completes and returns a ValidatedOutput or Rejection
THEN the CheckpointManager SHALL serialize the full pipeline state
AND store the checkpoint with step index set to 2 (validator complete).

#### Scenario: Checkpoint data structure

WHEN a checkpoint is serialized
THEN it SHALL contain: session_id, pipeline_type, step_index, step_name, step_output, original_request, timestamp, and status (in_progress/completed/failed).

---

### Requirement: In-Memory State Storage with Optional DB Persistence

Checkpoints SHALL be stored in memory by default, with optional database persistence configurable via application settings.

In-memory storage MUST use a thread-safe, async-compatible data structure.

#### Scenario: Default in-memory storage

WHEN checkpoint persistence is not configured
THEN checkpoints SHALL be stored in an in-memory dict keyed by session_id
AND the dict SHALL be protected by an async lock to prevent concurrent write corruption.

#### Scenario: Optional database persistence

WHEN checkpoint persistence is enabled in configuration
THEN checkpoints SHALL also be written to a `pipeline_checkpoint` table in PostgreSQL
AND the database record SHALL mirror the in-memory structure.

#### Scenario: Memory checkpoint eviction

WHEN the in-memory checkpoint store exceeds its configured maximum size
THEN the oldest checkpoints SHALL be evicted first (FIFO)
AND evicted checkpoints SHALL NOT affect persisted database copies if persistence is enabled.

---

### Requirement: Resume from Checkpoint

On pipeline start, the system SHALL check for an existing checkpoint and resume from the last completed step if one exists.

The resume MUST skip already-completed steps and continue with the next step in the pipeline.

#### Scenario: Resume after planner step

WHEN a pipeline is started and a checkpoint exists showing the planner step completed
THEN the pipeline SHALL skip the planner step
AND start execution from the executor step using the serialized ExecutionPlan from the checkpoint.

#### Scenario: Resume after executor step

WHEN a pipeline is started and a checkpoint exists showing the executor step completed
THEN the pipeline SHALL skip both planner and executor steps
AND start execution from the validator step using the serialized RawResult from the checkpoint.

#### Scenario: No checkpoint starts from beginning

WHEN a pipeline is started and no checkpoint exists for the session_id
THEN the pipeline SHALL execute from the planner step as normal
AND create a new checkpoint after each subsequent step.

#### Scenario: Checkpoint cleanup after pipeline completion

WHEN the pipeline completes all steps successfully
THEN the checkpoint for that session_id SHALL be deleted
AND the deletion SHALL occur after the HTTP response is sent to the client.

---

### Requirement: Dirty State Cleanup

On application startup, the system SHALL detect and clean orphaned checkpoints older than a configurable TTL.

Orphaned checkpoints (from crashed or abandoned pipelines) MUST NOT accumulate indefinitely.

#### Scenario: Cleanup orphaned checkpoints on startup

WHEN the application starts and checkpoints exist that are older than the configured TTL (default 1 hour)
THEN the CheckpointManager SHALL delete all expired checkpoints
AND log the number of cleaned checkpoints.

#### Scenario: TTL is configurable

WHEN the checkpoint TTL is set to 30 minutes in configuration
THEN checkpoints older than 30 minutes SHALL be considered orphaned
AND cleaned on the next startup or periodic cleanup cycle.

#### Scenario: Periodic cleanup runs during operation

WHEN the application is running
THEN the CheckpointManager SHALL run periodic cleanup every N minutes (configurable, default 10)
AND each cleanup cycle SHALL remove checkpoints older than the TTL.

---

### Requirement: Process Leak Management

The system SHALL track in-flight async tasks and cancel orphaned tasks on shutdown.

No async task related to a pipeline SHALL be left running after the application shuts down.

#### Scenario: Track in-flight pipeline tasks

WHEN a pipeline starts execution
THEN the task SHALL be registered in an in-flight task registry with session_id and creation timestamp
AND the registry SHALL be queryable for active pipeline tasks.

#### Scenario: Cancel orphaned tasks on shutdown

WHEN the application receives a shutdown signal
THEN the CheckpointManager SHALL cancel all in-flight pipeline tasks
AND each cancelled task SHALL log a shutdown cancellation event with its session_id.

#### Scenario: Detect long-running tasks

WHEN a pipeline task runs longer than a configured timeout (default 5 minutes)
THEN the system SHALL log a warning with the session_id and elapsed time
AND the task SHALL be marked as potentially stalled in the registry.

---

### Requirement: Graceful Cancellation via AbortSignal

The system SHALL propagate a cancellation signal from the frontend through the agent pipeline to async LLM calls.

When a user cancels a request in the frontend, all in-flight work SHALL be terminated gracefully.

#### Scenario: Frontend triggers cancellation

WHEN the frontend sends a cancellation request (e.g., client disconnects or explicit cancel button)
THEN the API layer SHALL set the abort signal on the pipeline context
AND the signal SHALL propagate to all running agents.

#### Scenario: Agent respects abort signal during LLM call

WHEN an abort signal is received while an agent is waiting for an LLM response
THEN the LLM call SHALL be cancelled immediately
AND the agent SHALL return a `CancelledError` with a partial result if available.

#### Scenario: Cleanup on cancellation

WHEN a pipeline is cancelled mid-execution
THEN the checkpoint SHALL be saved with status `cancelled` and the last completed step index
AND in-flight async resources (HTTP connections, stream readers) SHALL be released.

#### Scenario: Cancellation event logged

WHEN a pipeline is cancelled
THEN a telemetry event SHALL be recorded with type `pipeline_cancelled`
AND the event SHALL include the session_id, the step at which cancellation occurred, and the elapsed time.
