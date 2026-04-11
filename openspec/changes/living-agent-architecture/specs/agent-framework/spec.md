# Agent Framework (Modified)

## MODIFIED Requirements

### Requirement: AgentBase Abstract Class

The system SHALL provide an abstract base class `AgentBase` that defines the contract for all agents.

Every concrete agent MUST implement the following interface:
- `run(input)` — async method that accepts typed input and returns typed output
- `validate(input)` — async method that checks whether the input satisfies the agent's preconditions
- `name` — read-only property returning a unique string identifier for the agent
- `can_handle(input)` — async method that returns a float (0.0–1.0) indicating confidence this agent can handle the input

All agents SHALL be stateless with respect to request data; pipeline state MUST be passed explicitly through method arguments.

#### Scenario: Concrete agent implements required interface

- **WHEN** a developer creates a new agent by subclassing `AgentBase`
- **THEN** the subclass MUST provide implementations for `run()`, `validate()`, `name`, and `can_handle()`
- **AND** the agent SHALL raise `NotImplementedError` if any of these are left unimplemented.

#### Scenario: Agent validate rejects invalid input

- **WHEN** `validate(input)` is called with input that does not satisfy the agent's preconditions
- **THEN** the method SHALL raise a `ValidationError` with a descriptive message
- **AND** `run()` MUST NOT be invoked on invalid input.

#### Scenario: Agent name is unique and stable

- **WHEN** two agents are registered in the same pipeline
- **THEN** their `name` properties MUST return distinct values
- **AND** the name SHALL NOT change between invocations for the same agent instance.

#### Scenario: can_handle returns confidence score

- **WHEN** `can_handle(input)` is called with a request payload
- **THEN** the method SHALL return a float between 0.0 and 1.0
- **AND** a score >= 0.5 indicates the agent is a candidate to handle the request
- **AND** a score of 0.0 means the agent cannot handle the request.

---

### Requirement: PlannerAgent

The system SHALL provide a `PlannerAgent` that takes a user request and returns an execution plan.

The PlannerAgent MUST:
- Accept raw user input (natural language query plus optional context)
- Analyze the request intent and determine which capabilities are needed
- Select a `PlanningStrategy` based on input characteristics (complexity, attachments, template presence)
- Return a structured `ExecutionPlan` containing ordered steps with conditional branches

When re-invoked during self-correction, the PlannerAgent SHALL also accept the previous `Rejection` as context.

#### Scenario: Planner produces valid execution plan

- **WHEN** a user request is passed to `PlannerAgent.run()`
- **THEN** it SHALL return an `ExecutionPlan` with at least one step
- **AND** each step MUST reference a registered agent name or tool name from `SkillRegistry`.

#### Scenario: Planner handles ambiguous request

- **WHEN** the user request does not clearly map to a single capability
- **THEN** the PlannerAgent SHALL return an `ExecutionPlan` that includes a clarification step
- **AND** the clarification step MUST describe what additional information is needed.

#### Scenario: Planner selects strategy by input complexity

- **WHEN** a contract review request contains multiple attachments with complex dispute tags
- **THEN** the PlannerAgent SHALL select a multi-step strategy (e.g., extract → analyze → cross-reference → review)
- **AND** the strategy SHALL produce more steps than a simple single-attachment request.

#### Scenario: Planner re-plans after rejection

- **WHEN** the PlannerAgent receives a Rejection with reasons during self-correction
- **THEN** it SHALL generate a modified ExecutionPlan that addresses the rejection reasons
- **AND** the new plan MAY use different tools, different parameters, or additional steps.

---

### Requirement: ExecutionPlan DAG Support

The `ExecutionPlan` SHALL support conditional branches via a `condition` field on each `PlanStep`.

Steps with the same `parallel_group` value MAY be executed concurrently. Steps without a `parallel_group` SHALL execute sequentially.

#### Scenario: Conditional branch in execution plan

- **WHEN** a PlanStep has `condition="has_attachments == true"`
- **AND** the execution context contains `has_attachments: true`
- **THEN** the step SHALL execute
- **AND** if the condition evaluates to false, the step SHALL be skipped.

#### Scenario: Sequential execution by default

- **WHEN** a PlanStep does not have a `parallel_group` field
- **THEN** the step SHALL execute after the previous step completes
- **AND** steps SHALL execute in the order they appear in the plan.

---

### Requirement: ValidatorAgent

The system SHALL provide a `ValidatorAgent` that takes a raw result and returns validated output or a rejection.

The ValidatorAgent MUST:
- Accept a `RawResult` from an ExecutorAgent
- Apply a chain of `ValidationRule` instances (schema conformance + business rules + quality assessment)
- Return either a `ValidatedOutput` (wrapped, typed result) or a `Rejection` with reasons

Each `ValidationRule` SHALL classify its failure as either `retryable` or `non_retryable`, which the self-correction loop uses to decide whether to retry.

#### Scenario: Validator approves result

- **WHEN** a `RawResult` satisfies all validation rules
- **THEN** `ValidatorAgent.run()` SHALL return a `ValidatedOutput` containing the typed result
- **AND** the validated output MUST conform to the expected Pydantic model schema.

#### Scenario: Validator rejects with retryable reason

- **WHEN** a `RawResult` fails a validation rule that is marked as `retryable=True` (e.g., output_too_short, missing_citations)
- **THEN** the Validator SHALL return a `Rejection` with reasons including the retryable flag
- **AND** the Pipeline self-correction loop MAY retry.

#### Scenario: Validator rejects with non-retryable reason

- **WHEN** a `RawResult` fails a validation rule that is marked as `retryable=False` (e.g., permission_denied, tool_not_found)
- **THEN** the Validator SHALL return a `Rejection` with reasons including the non-retryable flag
- **AND** the Pipeline self-correction loop SHALL NOT retry.

#### Scenario: Validator applies rule chain in order

- **WHEN** multiple validation rules are configured
- **THEN** the rules SHALL execute in registration order
- **AND** the first failing rule SHALL produce the rejection reason
- **AND** subsequent rules SHALL NOT execute after the first failure.
