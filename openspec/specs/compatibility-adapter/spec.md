# Compatibility Adapter

## ADDED Requirements

### Requirement: API Compatibility Adapter

The system SHALL provide a `CompatibilityAdapter` that converts internal agent pipeline results and events into the repository's existing external API contracts.

The adapter MUST preserve the JSON shapes, field names, status semantics, and streaming event formats currently consumed by the frontend.

#### Scenario: Non-streaming endpoint preserves legacy response shape

WHEN an agent-backed non-streaming endpoint returns a validated internal result
THEN the compatibility adapter SHALL transform it into the same response shape previously returned by the legacy service implementation
AND existing frontend code SHALL not require any changes to parse the result.

#### Scenario: Streaming endpoint preserves legacy event contract

WHEN an agent-backed streaming endpoint emits internal events such as planning or validation milestones
THEN the compatibility adapter SHALL map or suppress those internal events so that the client receives only the established streaming event contract
AND newly introduced internal event types SHALL NOT leak directly to existing clients unless a new public API version explicitly declares them.

#### Scenario: Adapter preserves HTTP error semantics

WHEN the agent pipeline returns a validation rejection, governance block, timeout, or internal execution failure
THEN the compatibility adapter SHALL return the same HTTP status code and external error payload shape defined by the existing endpoint contract
AND the adapter SHALL hide internal implementation details that are not part of the public API.

---

### Requirement: Compatibility Verification

Every migrated endpoint SHALL be verified against golden contract fixtures captured from the legacy implementation.

The compatibility verification MUST cover both non-streaming JSON responses and streaming NDJSON / SSE payloads where applicable.

#### Scenario: Golden response test passes for migrated endpoint

WHEN a migrated endpoint is exercised with a fixture request used against the legacy service
THEN the compatibility test SHALL confirm that the adapted response matches the expected public contract
AND any intentional differences SHALL require explicit approval and versioned API documentation updates.

#### Scenario: Streaming compatibility test validates event sequence

WHEN a migrated streaming endpoint is exercised with a fixture request
THEN the compatibility test SHALL verify event ordering, event types, and required payload fields against the legacy contract
AND the test SHALL fail if internal-only events are emitted to the public stream.
