# Agent Orchestrator

## ADDED Requirements

### Requirement: Orchestrator Agent Central Dispatch

The system SHALL provide an `OrchestratorAgent` that receives all user requests and autonomously determines which Agent(s) to invoke, in what order, and with what parameters.

The Orchestrator MUST replace the hardcoded if-else routing logic currently in `routers/search.py` and `routers/prediction.py`.

#### Scenario: Simple chat request routed to ChatAgent

- **WHEN** a request arrives at `POST /api/chat/stream` with a standard chat payload
- **THEN** the Orchestrator SHALL identify the intent as "grounded_chat" and dispatch to the Chat Pipeline
- **AND** the behavior SHALL be identical to the current hardcoded routing.

#### Scenario: Contract review request routed to ContractReview pipeline

- **WHEN** a request arrives at `POST /api/contract-review/stream` with session_id and template_id
- **THEN** the Orchestrator SHALL identify the intent as "contract_review" and dispatch to the ContractReview Pipeline
- **AND** the behavior SHALL be identical to the current hardcoded routing.

#### Scenario: Similar case search routed to SimilarCase pipeline

- **WHEN** a request arrives at `POST /api/similar-cases/compare`
- **THEN** the Orchestrator SHALL identify the intent as "similar_case_search" and dispatch to the SimilarCase Pipeline.

#### Scenario: Opponent prediction routed to Prediction pipeline

- **WHEN** a request arrives at `POST /api/opponent-prediction/start` with template_id and query
- **THEN** the Orchestrator SHALL identify the intent as "opponent_prediction" and dispatch to the Prediction Pipeline.

#### Scenario: Unknown intent falls back to Chat pipeline

- **WHEN** a request arrives that does not match any known intent pattern
- **THEN** the Orchestrator SHALL fall back to the Chat Pipeline as the default handler
- **AND** a telemetry event SHALL be recorded with intent=`unknown`.

---

### Requirement: IntentRouter Deterministic Classification

The Orchestrator SHALL use an `IntentRouter` that classifies requests based on deterministic rules (API endpoint path + payload structure), NOT LLM inference.

The IntentRouter MUST map each combination to a registered pipeline name.

#### Scenario: Intent classified by endpoint path

- **WHEN** a request to `/api/contract-review/stream` is received
- **THEN** the IntentRouter SHALL return intent=`contract_review` based on the endpoint path alone
- **AND** no LLM call SHALL be made for classification.

#### Scenario: Intent classified by payload fields

- **WHEN** a request to `/api/chat/stream` contains `template_id` and `session_id` fields indicating a review follow-up
- **THEN** the IntentRouter MAY classify the intent as `contract_review_continuation`
- **AND** the Orchestrator SHALL dispatch accordingly.

#### Scenario: All current routes covered

- **WHEN** the IntentRouter is initialized
- **THEN** it SHALL contain rules for ALL existing API endpoints that currently trigger Agent Pipelines
- **AND** the behavior SHALL be backward-compatible with the current routing.

---

### Requirement: Orchestrator Dispatches via SkillRegistry

The Orchestrator SHALL resolve the target pipeline through `SkillRegistry.discover()`, not through direct import.

#### Scenario: Pipeline resolved by name

- **WHEN** the IntentRouter returns intent=`similar_case_search`
- **THEN** the Orchestrator SHALL call `SkillRegistry.discover("similar_case_search")` to obtain the pipeline factory
- **AND** SHALL create and execute the pipeline.

#### Scenario: Unregistered intent raises SkillNotFoundError

- **WHEN** the IntentRouter returns an intent name that is not registered in SkillRegistry
- **THEN** the Orchestrator SHALL fall back to the default Chat pipeline
- **AND** SHALL log a warning with the unregistered intent name.

---

### Requirement: Orchestrator Delegates to Agent Pipelines

The Orchestrator SHALL NOT contain business logic. It SHALL only: (1) classify intent, (2) resolve pipeline, (3) execute pipeline, (4) return result.

#### Scenario: Orchestrator does not process data

- **WHEN** the Orchestrator dispatches a request to a pipeline
- **THEN** it SHALL pass the raw request data to the pipeline WITHOUT modification
- **AND** it SHALL return the pipeline result to the caller WITHOUT transformation.
