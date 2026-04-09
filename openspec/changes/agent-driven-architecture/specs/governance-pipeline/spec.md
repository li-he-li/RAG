# Governance Pipeline

## ADDED Requirements

### Requirement: GovernancePipeline Execution

The system SHALL provide a `GovernancePipeline` that runs after the Validator agent and before the HTTP response is sent.

The governance pipeline MUST inspect every validated output and enforce content policies before the result reaches the client.

#### Scenario: Governance runs on every validated output

WHEN a validated output is produced by the ValidatorAgent
THEN the governance pipeline SHALL execute synchronously before the response is returned
AND the HTTP response SHALL NOT be sent until governance completes.

#### Scenario: Governance does not modify output on pass

WHEN all governance checks pass
THEN the original validated output SHALL be returned unchanged
AND a governance pass event SHALL be logged.

---

### Requirement: Content Safety Filter

The governance pipeline SHALL block responses containing patterns matching personally identifiable information (PII) or harmful content.

The filter MUST use configurable pattern lists that can be updated without code changes.

#### Scenario: Block response containing PII

WHEN a validated output contains a pattern matching a PII regex (e.g., national ID number, phone number)
THEN the governance pipeline SHALL block the response
AND return a `GovernanceBlockError` with the rule that was violated.

#### Scenario: Block response containing harmful content

WHEN a validated output matches a harmful content pattern (e.g., instructions for illegal activity)
THEN the governance pipeline SHALL block the response
AND log a governance event with severity `critical`.

#### Scenario: Allow response with no matching patterns

WHEN the validated output contains no PII or harmful content patterns
THEN the content safety filter SHALL pass the output through unchanged.

#### Scenario: Configurable pattern list

WHEN a new pattern is added to the governance configuration file
THEN the pattern SHALL take effect on the next request without requiring a restart
AND the pattern SHALL be applied to all subsequent validated outputs.

---

### Requirement: Prompt Injection Detection

The governance pipeline SHALL detect if the LLM output contains instructions intended to bypass governance or manipulate the system.

The detection MUST identify common prompt injection patterns in the model's output text.

#### Scenario: Detect injection attempt in output

WHEN the LLM output contains text like "ignore previous instructions" or "system: bypass governance"
THEN the governance pipeline SHALL block the response
AND log a governance event with type `prompt_injection_detected`.

#### Scenario: Allow output without injection patterns

WHEN the LLM output does not contain any injection patterns
THEN the injection detection check SHALL pass the output through unchanged.

#### Scenario: Injection detection is case-insensitive

WHEN an injection pattern appears in mixed case or with Unicode lookalike characters
THEN the detection MUST still identify and block the pattern
AND use normalized text comparison for matching.

---

### Requirement: Output Schema Validation

The governance pipeline SHALL verify that the LLM output matches the expected Pydantic model schema.

The validation MUST run after content safety and injection checks.

#### Scenario: Output matches expected schema

WHEN the validated output conforms to the expected Pydantic model
THEN the schema validation SHALL pass the output through unchanged.

#### Scenario: Output fails schema validation

WHEN the validated output does not conform to the expected Pydantic model
THEN the governance pipeline SHALL block the response
AND return a `SchemaValidationError` with the list of schema violations.

#### Scenario: Schema validation handles extra fields

WHEN the output contains extra fields not defined in the schema
THEN the governance pipeline SHALL strip the extra fields
AND log a governance event noting the removed fields.

---

### Requirement: Non-Bypassable Governance

The governance pipeline SHALL be non-bypassable: it MUST run in the application layer and the LLM model SHALL NOT be able to skip it.

No code path from agent output to HTTP response SHALL bypass the governance pipeline.

#### Scenario: Governance cannot be skipped by agent

WHEN any agent in the pipeline attempts to return output directly to the HTTP response
THEN the framework SHALL route the output through the governance pipeline first
AND there SHALL be no API or method to disable governance for individual requests.

#### Scenario: Governance is enforced for all response paths

WHEN a response is returned via streaming, synchronous return, or error recovery
THEN governance checks SHALL apply to all paths equally
AND the streaming path MUST apply governance to each chunk before it is sent.

---

### Requirement: Governance Audit Log

The governance pipeline SHALL record all governance decisions (pass, block, log) in an audit log.

Every governance event MUST be persisted and queryable for compliance review.

#### Scenario: Log governance pass event

WHEN all governance checks pass for a response
THEN an audit log entry SHALL be created with: timestamp, correlation_id, decision=`pass`, rules_checked.

#### Scenario: Log governance block event

WHEN a governance check blocks a response
THEN an audit log entry SHALL be created with: timestamp, correlation_id, decision=`block`, violated_rule, rule_pattern_matched, severity.

#### Scenario: Audit log is queryable

WHEN a compliance query is made for governance events within a date range
THEN the system SHALL return all matching log entries
AND entries MUST be filterable by decision type (pass/block), rule name, and severity.
