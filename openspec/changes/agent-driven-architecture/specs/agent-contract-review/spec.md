# Agent Contract Review

## ADDED Requirements

### Requirement: ContractReviewPlanner

The system SHALL provide a `ContractReviewPlanner` agent that splits contract clauses and selects a template matching strategy.

The planner MUST:
- Accept a contract document (uploaded file or text content)
- Parse and split the document into individual clauses or sections
- Identify the contract type and select the appropriate review template
- Return an execution plan with clauses, matched template, and analysis strategy

#### Scenario: Planner splits contract into clauses

WHEN a contract document is passed to `ContractReviewPlanner.run()`
THEN the planner SHALL parse the document and split it into a list of clauses
AND each clause MUST include its section heading, content text, and position index.

#### Scenario: Planner matches contract type to template

WHEN the planner identifies the contract as a specific type (e.g., employment, lease, sales)
THEN it SHALL select the corresponding review template from the template registry
AND the execution plan MUST reference the matched template ID and name.

#### Scenario: Planner handles unrecognized contract type

WHEN the contract type cannot be determined from the document content
THEN the planner SHALL select a generic review template as fallback
AND the execution plan MUST include a flag indicating the template was auto-selected with low confidence.

---

### Requirement: ContractReviewExecutor

The system SHALL provide a `ContractReviewExecutor` agent that runs difference analysis and calls the LLM for review.

The executor MUST:
- Accept the execution plan from `ContractReviewPlanner`
- Compare each clause against the matched template to identify deviations
- Call the LLM to generate review findings for each deviating clause
- Yield streaming events for each clause as it is reviewed
- Return a raw result containing all findings

#### Scenario: Executor runs clause-by-clause analysis

WHEN `ContractReviewExecutor.run()` receives a plan with 10 clauses
THEN the executor SHALL analyze each clause against the template
AND produce findings for clauses that deviate from the template standard.

#### Scenario: Executor streams findings progressively

WHEN `ContractReviewExecutor.stream()` is invoked
THEN it SHALL yield an NDJSON event for each clause finding as it is produced
AND each event MUST include the clause index, finding type, and finding content.

#### Scenario: Executor handles clause with no deviation

WHEN a clause matches the template standard with no deviations
THEN the executor SHALL produce a finding with status `compliant`
AND the finding MUST note that the clause meets the template standard.

---

### Requirement: ContractReviewValidator

The system SHALL provide a `ContractReviewValidator` agent that validates findings consistency and checks coverage.

The validator MUST:
- Accept the raw result from `ContractReviewExecutor`
- Verify that every clause in the original plan has a corresponding finding
- Check that findings do not contradict each other
- Validate that risk levels are consistently assigned

#### Scenario: Validator confirms full clause coverage

WHEN the validator receives findings for all clauses in the plan
THEN it SHALL return a validated output confirming 100% clause coverage.

#### Scenario: Validator detects missing clause findings

WHEN one or more clauses lack corresponding findings
THEN the validator SHALL flag the missing clauses in a validation warning
AND attempt to generate placeholder findings with status `unreviewed`.

#### Scenario: Validator detects inconsistent risk levels

WHEN two findings for the same clause have conflicting risk level assignments
THEN the validator SHALL resolve the conflict by selecting the higher risk level
AND log the resolution as a validation adjustment.

---

### Requirement: Streaming Format Compatibility

The contract review agent pipeline SHALL return the same streaming NDJSON format as the current `/api/predict` endpoint.

Every event yielded by the pipeline MUST use the same event types and field structure as the current streaming implementation.

#### Scenario: Streaming events match current format

WHEN the pipeline streams contract review events
THEN each event SHALL use the same JSON structure as events from the current streaming endpoint
AND event type names MUST match: `clause_start`, `finding`, `review_complete`.

#### Scenario: Frontend consumes stream without changes

WHEN the frontend SSE/EventSource handler processes the pipeline output
THEN it SHALL parse events successfully without any code changes
AND the rendered review report MUST be visually identical to the current output.

---

### Requirement: Integration with Existing Review Services

The contract review agent pipeline SHALL integrate with the existing contract review and file extraction services.

The pipeline MUST use the existing `file_extract.py` for document parsing and the existing LLM call patterns for review generation.

#### Scenario: Pipeline uses existing file extraction

WHEN a contract file is uploaded for review
THEN the pipeline SHALL use `file_extract.py` to parse the document content
AND the parsed output MUST be identical to what the current service produces.

#### Scenario: Pipeline uses existing LLM call pattern

WHEN the executor generates review findings
THEN it SHALL call the LLM using the same service function and parameters as the current implementation
AND the LLM response handling MUST follow the existing error-retry and fallback logic.
