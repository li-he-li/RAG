# Tool Governance (Modified)

## MODIFIED Requirements

### Requirement: Tool Allowlist Enforcement

The system SHALL provide a `ToolGovernancePolicy` that governs every tool invocation initiated by an agent.

Only tools registered in an explicit allowlist MAY be invoked by PlannerAgent or ExecutorAgent code paths.

The allowlist SHALL include both function-based tools AND Agent-as-Tool entries. Agent-as-Tool entries SHALL be registered with side_effect_level=`READ_ONLY` unless explicitly configured otherwise.

#### Scenario: Allowed tool executes

- **WHEN** an agent attempts to invoke a tool that is present in the configured allowlist
- **THEN** the governance policy SHALL permit execution to proceed
- **AND** the invocation SHALL be logged with tool name, agent name, correlation ID, and normalized parameters.

#### Scenario: Unregistered tool is blocked

- **WHEN** an agent attempts to invoke a tool that is not present in the allowlist
- **THEN** the governance policy SHALL block the invocation before the tool executes
- **AND** the system SHALL record an audit entry with decision=`block` and reason=`tool_not_allowed`.

#### Scenario: Agent-as-Tool invocation is governed

- **WHEN** an agent invokes another agent registered as a tool via `invoke_tool()`
- **THEN** the ToolGovernancePolicy SHALL enforce the same allowlist and schema validation as function-based tools
- **AND** the recursion depth SHALL be checked against the maximum allowed depth.

---

### Requirement: Recursion Depth Enforcement

The ToolGovernancePolicy SHALL enforce a maximum recursion depth for Agent-to-Agent invocations.

The default maximum depth SHALL be 3. This limit SHALL NOT be overridable by any Agent or model output.

#### Scenario: Recursion depth within limit

- **WHEN** an Agent-to-Agent invocation occurs at depth < max_depth
- **THEN** the ToolGovernancePolicy SHALL allow the invocation to proceed.

#### Scenario: Recursion depth exceeded

- **WHEN** an Agent-to-Agent invocation would exceed the maximum recursion depth
- **THEN** the ToolGovernancePolicy SHALL block the invocation
- **AND** SHALL log an audit entry with reason=`recursion_depth_exceeded`
- **AND** SHALL raise a `GovernanceBlockError` back to the calling agent.
