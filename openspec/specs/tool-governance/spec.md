# Tool Governance

## ADDED Requirements

### Requirement: Tool Allowlist Enforcement

The system SHALL provide a `ToolGovernancePolicy` that governs every tool invocation initiated by an agent.

Only tools registered in an explicit allowlist MAY be invoked by PlannerAgent or ExecutorAgent code paths.

#### Scenario: Allowed tool executes

WHEN an agent attempts to invoke a tool that is present in the configured allowlist
THEN the governance policy SHALL permit execution to proceed
AND the invocation SHALL be logged with tool name, agent name, correlation ID, and normalized parameters.

#### Scenario: Unregistered tool is blocked

WHEN an agent attempts to invoke a tool that is not present in the allowlist
THEN the governance policy SHALL block the invocation before the tool executes
AND the system SHALL record an audit entry with decision=`block` and reason=`tool_not_allowed`.

---

### Requirement: Parameter Schema Validation

Every governed tool SHALL define a machine-validatable input schema.

Tool invocations MUST be validated against the schema before execution, and invalid arguments MUST be rejected without side effects.

#### Scenario: Invalid tool arguments are rejected pre-execution

WHEN an agent supplies arguments that do not conform to the governed tool's schema
THEN the governance policy SHALL reject the invocation before the tool runs
AND the rejection SHALL include the schema validation errors in audit metadata.

#### Scenario: Normalized parameters are passed to tool

WHEN an agent supplies schema-valid arguments
THEN the governance layer SHALL pass the normalized, validated parameters to the tool implementation
AND the executed tool SHALL NOT receive raw unvalidated input from the agent.

---

### Requirement: Side-Effect Tool Approval Policy

Governed tools SHALL be classified by side-effect level.

Read-only tools MAY execute automatically. Stateful or externally visible tools MUST follow an approval policy defined outside the model.

#### Scenario: Read-only retrieval tool auto-executes

WHEN an agent invokes a read-only tool such as retrieval or re-ranking
THEN the governance policy MAY allow automatic execution if the tool is allowlisted and schema-valid.

#### Scenario: Stateful tool requires policy approval

WHEN an agent invokes a tool that mutates state, triggers external actions, or changes persistent data
THEN the governance policy SHALL require an explicit non-model approval rule before execution
AND the tool SHALL NOT run unless the approval requirement is satisfied.

#### Scenario: Approval logic cannot be overridden by model output

WHEN the model output requests that a side-effect tool be forced to run
THEN the governance policy SHALL ignore the model's instruction unless the external approval rule allows execution
AND the decision path SHALL be auditable.

---

### Requirement: Pre-Execution Injection Defense

Governance SHALL inspect tool-bound inputs for prompt injection or policy-override attempts before tool execution.

The defense MUST run on agent-produced tool requests and on untrusted retrieved / uploaded content routed into tool parameters.

#### Scenario: Retrieved text attempts to alter tool behavior

WHEN retrieved or uploaded content contains instructions such as "ignore governance" or attempts to alter downstream tool calls
THEN the governance layer SHALL treat that content as untrusted data rather than executable instruction
AND any blocked invocation SHALL produce an audit event with reason=`tool_input_injection_detected`.

---

### Requirement: Tool Governance Audit Log

Every governed tool decision SHALL be persisted in a queryable audit log.

The log MUST capture allow, block, and approval-required decisions.

#### Scenario: Audit entry created for allowed tool call

WHEN a governed tool executes successfully
THEN the audit log SHALL record timestamp, correlation_id, agent_name, tool_name, decision=`allow`, and a parameter summary.

#### Scenario: Audit entry created for blocked tool call

WHEN a governed tool invocation is blocked
THEN the audit log SHALL record timestamp, correlation_id, agent_name, tool_name, decision=`block`, and the violated policy reason.
