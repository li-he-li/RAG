# Agent Framework

## ADDED Requirements

### Requirement: AgentBase Abstract Class

The system SHALL provide an abstract base class `AgentBase` that defines the contract for all agents.

Every concrete agent MUST implement the following interface:
- `run(input)` — async method that accepts typed input and returns typed output
- `validate(input)` — async method that checks whether the input satisfies the agent's preconditions
- `name` — read-only property returning a unique string identifier for the agent

All agents SHALL be stateless with respect to request data; pipeline state MUST be passed explicitly through method arguments.

#### Scenario: Concrete agent implements required interface

WHEN a developer creates a new agent by subclassing `AgentBase`
THEN the subclass MUST provide implementations for `run()`, `validate()`, and the `name` property
AND the agent SHALL raise `NotImplementedError` if any of these are left unimplemented.

#### Scenario: Agent validate rejects invalid input

WHEN `validate(input)` is called with input that does not satisfy the agent's preconditions
THEN the method SHALL raise a `ValidationError` with a descriptive message
AND `run()` MUST NOT be invoked on invalid input.

#### Scenario: Agent name is unique and stable

WHEN two agents are registered in the same pipeline
THEN their `name` properties MUST return distinct values
AND the name SHALL NOT change between invocations for the same agent instance.

---

### Requirement: PlannerAgent

The system SHALL provide a `PlannerAgent` that takes a user request and returns an execution plan.

The PlannerAgent MUST:
- Accept raw user input (natural language query plus optional context)
- Analyze the request intent and determine which capabilities are needed
- Return a structured `ExecutionPlan` containing ordered steps, each with a target agent name, input mapping, and expected output type

#### Scenario: Planner produces valid execution plan

WHEN a user request is passed to `PlannerAgent.run()`
THEN it SHALL return an `ExecutionPlan` with at least one step
AND each step MUST reference a registered agent name from `SkillRegistry`.

#### Scenario: Planner handles ambiguous request

WHEN the user request does not clearly map to a single capability
THEN the PlannerAgent SHALL return an `ExecutionPlan` that includes a clarification step
AND the clarification step MUST describe what additional information is needed.

---

### Requirement: ExecutorAgent

The system SHALL provide an `ExecutorAgent` that takes an execution plan and returns a raw result.

The ExecutorAgent MUST:
- Accept an `ExecutionPlan` produced by a PlannerAgent
- Execute each step in order, passing outputs from prior steps as inputs to subsequent steps
- Return a `RawResult` containing the final output and intermediate step results

#### Scenario: Executor runs plan steps sequentially

WHEN an `ExecutionPlan` with multiple steps is passed to `ExecutorAgent.run()`
THEN steps SHALL be executed in the order defined by the plan
AND the output of step N MUST be available as input to step N+1.

#### Scenario: Executor handles step failure

WHEN a step in the execution plan raises an exception
THEN the ExecutorAgent SHALL stop execution and return a `RawResult` with status `failed`
AND the result MUST include the step index that failed and the exception details.

---

### Requirement: ValidatorAgent

The system SHALL provide a `ValidatorAgent` that takes a raw result and returns validated output or a rejection.

The ValidatorAgent MUST:
- Accept a `RawResult` from an ExecutorAgent
- Check output completeness, schema conformance, and business-rule constraints
- Return either a `ValidatedOutput` (wrapped, typed result) or a `Rejection` with reasons

#### Scenario: Validator approves result

WHEN a `RawResult` satisfies all validation rules
THEN `ValidatorAgent.run()` SHALL return a `ValidatedOutput` containing the typed result
AND the validated output MUST conform to the expected Pydantic model schema.

#### Scenario: Validator rejects result

WHEN a `RawResult` fails one or more validation rules
THEN `ValidatorAgent.run()` SHALL return a `Rejection` with a list of failure reasons
AND the rejection MUST indicate which rules failed and the associated field values.

---

### Requirement: AgentPipeline

The system SHALL provide an `AgentPipeline` that chains Planner, Executor, and Validator with streaming support.

The pipeline MUST:
- Accept a user request and route it through Planner -> Executor -> Validator
- Support streaming: yield partial results as NDJSON events via an async generator
- Be compatible with `fastapi.responses.StreamingResponse`

#### Scenario: Full pipeline produces final validated result

WHEN a user request is submitted to `AgentPipeline.run()`
THEN the pipeline SHALL invoke PlannerAgent, then ExecutorAgent, then ValidatorAgent in sequence
AND return the final `ValidatedOutput`.

#### Scenario: Pipeline streams intermediate events

WHEN a user request is submitted to `AgentPipeline.stream()`
THEN the pipeline SHALL yield NDJSON events for each agent transition (plan_created, step_started, step_completed, validation_passed)
AND the event stream MUST be consumable by `StreamingResponse`.

#### Scenario: Pipeline propagates validation rejection

WHEN the ValidatorAgent returns a `Rejection`
THEN the pipeline SHALL NOT return the raw result to the caller
AND the pipeline MUST return a structured error response indicating the rejection reasons.

---

### Requirement: SkillRegistry

The system SHALL provide a `SkillRegistry` that allows registration and discovery of agent capabilities by name.

The SkillRegistry MUST:
- Provide `register(name, agent_class, metadata)` to add an agent
- Provide `discover(name)` to retrieve a registered agent class and its metadata
- Provide `list_capabilities()` to return all registered agent names with descriptions

#### Scenario: Register and discover an agent

WHEN an agent is registered via `SkillRegistry.register("similar_case", SimilarCasePlanner, {...})`
THEN a subsequent call to `SkillRegistry.discover("similar_case")` SHALL return the registered class and metadata.

#### Scenario: Discover unregistered agent raises error

WHEN `SkillRegistry.discover("nonexistent")` is called for an agent that was never registered
THEN the registry SHALL raise a `SkillNotFoundError`.

#### Scenario: List all capabilities

WHEN `SkillRegistry.list_capabilities()` is called
THEN it SHALL return a list of all registered agent names with their metadata descriptions
AND the list SHALL be ordered by registration time.

---

### Requirement: Async and FastAPI Compatibility

All agents and pipelines SHALL be fully async and compatible with FastAPI's async request lifecycle.

Every agent's `run()` and `validate()` methods MUST be `async` functions. The pipeline's `stream()` method MUST return an async generator. The pipeline SHALL be usable directly as the source for `StreamingResponse`.

#### Scenario: Pipeline used in FastAPI endpoint

WHEN a FastAPI route handler creates a `StreamingResponse` with `pipeline.stream(request)` as the content source
THEN the response SHALL stream NDJSON events to the client without blocking the event loop.

#### Scenario: Concurrent pipeline invocations

WHEN multiple pipeline instances are invoked concurrently
THEN each invocation SHALL execute independently without shared mutable state
AND no invocation SHALL block another.
