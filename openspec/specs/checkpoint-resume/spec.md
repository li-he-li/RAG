# Robustness: Idempotent Retry, Graceful Cancellation, and Process Hygiene

> **Design decision**: Full checkpoint/resume (pipeline state serialization + resume from last completed step) has been descoped. Current pipeline latency is 5–40 seconds — users naturally retry rather than wait for a stale checkpoint to restore. If batch pipelines exceeding 10 minutes are introduced in the future, checkpoint/resume can be added without changing the AgentPipeline interface.

## ADDED Requirements

### Requirement: Idempotent Retry

The system SHALL support idempotent retry for pipeline requests.

When a client retransmits a request (e.g., due to network timeout), the system MUST detect the duplicate and handle it gracefully instead of running the full pipeline again.

#### Scenario: Duplicate request detected by session_id + request_hash

WHEN a pipeline request arrives with a session_id and request_hash that match a recently completed request
THEN the system SHALL return the cached result from the previous execution
AND the duplicate SHALL be logged as a telemetry event with type `idempotent_cache_hit`.

#### Scenario: Duplicate request while original is still in progress

WHEN a pipeline request arrives with a session_id and request_hash that match a currently executing request
THEN the system SHALL wait for the in-progress execution to complete and return its result
AND a second pipeline execution SHALL NOT be started.

#### Scenario: Cache entry expires after TTL

WHEN the TTL for an idempotent cache entry expires
THEN the entry SHALL be evicted from the cache
AND a subsequent request with the same session_id and request_hash SHALL trigger a new pipeline execution.

#### Scenario: Cache does not interfere with different requests

WHEN two requests share a session_id but have different request_hash values
THEN each SHALL be treated as a distinct request and executed independently.

---

### Requirement: Graceful Cancellation

The system SHALL propagate client disconnection / abort signals to cancel in-progress pipeline work.

When the client closes the connection or sends an AbortSignal, all associated async tasks MUST be cancelled promptly to release resources.

#### Scenario: Client disconnects during streaming

WHEN the client closes the SSE/NDJSON connection while the pipeline is still streaming
THEN the pipeline SHALL detect the disconnection within 2 seconds
AND cancel the in-progress LLM API call
AND release all resources associated with the request.

#### Scenario: Client disconnects during non-streaming request

WHEN the client disconnects before the non-streaming response is sent
THEN the pipeline SHALL cancel the remaining agent steps
AND log a telemetry event with type `request_cancelled`.

#### Scenario: Cancellation does not corrupt shared state

WHEN a pipeline is cancelled mid-execution
THEN no shared state (database records, vector store entries, temporary files) SHALL be left in an inconsistent state
AND any partial writes SHALL be rolled back or cleaned up.

---

### Requirement: Async Task Leak Management

The system SHALL track all background async tasks spawned by pipelines and ensure none outlive the application lifecycle.

#### Scenario: Background tasks tracked on creation

WHEN a pipeline spawns a background async task (e.g., trajectory write, telemetry flush)
THEN the task SHALL be registered in a central task tracker
AND the tracker SHALL maintain a reference to the task and its creation timestamp.

#### Scenario: Orphan tasks cancelled on shutdown

WHEN the application begins graceful shutdown
THEN all tracked background tasks SHALL be cancelled with a configurable grace period (default 5 seconds)
AND tasks that do not complete within the grace period SHALL be forcefully cancelled
AND the count of forcefully cancelled tasks SHALL be logged.

#### Scenario: Long-running tasks detected at runtime

WHEN a background task has been running for longer than its expected maximum duration (configurable per task type)
THEN the system SHALL log a warning with the task type, duration, and creation context
AND optionally cancel the task if configured to do so.

---

### Requirement: Dirty State Cleanup on Startup

On application startup, the system SHALL detect and clean orphaned temporary data from previous runs.

#### Scenario: Cleanup orphaned temporary files

WHEN the application starts
THEN it SHALL scan for temporary files older than a configurable TTL
AND delete orphaned files that are not associated with any active session.

#### Scenario: Cleanup orphaned idempotent cache entries

WHEN the application starts
THEN it SHALL clear the in-memory idempotent cache (since no in-progress requests survive a restart).

#### Scenario: Startup cleanup does not block request handling

WHEN startup cleanup is in progress
THEN incoming requests SHALL NOT be blocked by the cleanup process
AND cleanup SHALL run as a background task after the server begins accepting connections.
