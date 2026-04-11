# Agent Self-Correction

## ADDED Requirements

### Requirement: Self-Correction Loop in AgentPipeline

The `AgentPipeline` SHALL support a self-correction loop: when the Validator returns a `Rejection`, the Pipeline SHALL feed the rejection back to the Planner for re-planning, then re-execute and re-validate.

The loop SHALL respect a configurable `max_retries` limit (default: 2).

#### Scenario: Successful retry after first rejection

- **WHEN** the Validator rejects the Executor's output on the first attempt
- **AND** the Planner generates a modified ExecutionPlan based on the rejection reasons
- **AND** the Executor produces output that passes validation on the second attempt
- **THEN** the Pipeline SHALL return the validated output
- **AND** the trajectory log SHALL record both attempts with their respective step types.

#### Scenario: Max retries exhausted

- **WHEN** the Validator rejects the output for the third consecutive attempt (max_retries=2)
- **THEN** the Pipeline SHALL return the final `Rejection` to the caller
- **AND** the trajectory log SHALL record all attempts with failure reasons.

#### Scenario: Non-retryable error bypasses loop

- **WHEN** the Validator rejection reason indicates a non-retryable error (e.g., permission denied, tool not found)
- **THEN** the Pipeline SHALL NOT retry
- **AND** the Pipeline SHALL immediately return the Rejection.

#### Scenario: Retry count tracked in telemetry

- **WHEN** a self-correction loop completes (success or exhaustion)
- **THEN** the TelemetryService SHALL record an event with: intent, retry_count, final_outcome
- **AND** the event SHALL be queryable by correlation_id.

---

### Requirement: Planner Receives Rejection Feedback

When the self-correction loop triggers, the Planner SHALL receive the original request PLUS the `Rejection` (reasons + details) as input for re-planning.

#### Scenario: Planner modifies strategy based on rejection

- **WHEN** the Planner receives a Rejection with reasons=["missing_citations", "output_too_short"]
- **THEN** the Planner SHALL generate a modified ExecutionPlan that addresses the rejection reasons
- **AND** the new plan MAY include different tools, different parameters, or additional steps.

#### Scenario: Planner decides retry is futile

- **WHEN** the Planner receives a Rejection with reason=["permission_denied"]
- **THEN** the Planner SHALL signal that no retry is possible
- **AND** the Pipeline SHALL propagate the Rejection immediately.

---

### Requirement: Pipeline Without Planner Cannot Self-Correct

If the Pipeline topology is `[Executor → Validator]` (no Planner), the self-correction loop SHALL NOT activate. The rejection SHALL be returned directly.

#### Scenario: Executor-only pipeline returns rejection immediately

- **WHEN** a Pipeline with topology `[Executor → Validator]` receives a Rejection from the Validator
- **THEN** the Rejection SHALL be returned to the caller immediately
- **AND** no retry attempt SHALL be made.

---

### Requirement: Streaming Pipeline Self-Correction

For streaming pipelines, self-correction SHALL apply to the post-stream validation phase. If the post-stream Validator rejects, the Pipeline SHALL emit a `governance_retracted` event, NOT retry the stream.

#### Scenario: Post-stream validation failure in streaming mode

- **WHEN** the Validator rejects the aggregated stream result
- **THEN** the Pipeline SHALL emit a `validation_rejected` event to the client
- **AND** the streamed content SHALL be marked as invalid
- **AND** the Pipeline SHALL NOT re-stream a corrected response.
