# Agent-to-Agent Calls

## ADDED Requirements

### Requirement: Agent-as-Tool Registration

The system SHALL allow any Agent to be registered as a `GovernedTool` in the `ToolRegistry`, enabling other Agents to invoke it through the standard `invoke_tool()` mechanism.

#### Scenario: Register SimilarCaseAgent as a tool

- **WHEN** the system initializes
- **THEN** the SimilarCaseAgent SHALL be registered as a tool named `similar_case_search` in the ToolRegistry
- **AND** the tool SHALL have side_effect_level=`READ_ONLY`
- **AND** the tool schema SHALL define the expected input fields (request, db).

#### Scenario: Register ChatAgent as a tool

- **WHEN** the system initializes
- **THEN** the ChatAgent SHALL be registered as a tool named `grounded_chat` in the ToolRegistry
- **AND** the tool SHALL have side_effect_level=`READ_ONLY`.

#### Scenario: Agent tool invoked via invoke_tool

- **WHEN** the ContractReviewExecutor calls `self.invoke_tool("similar_case_search", {"request": {...}, "db": db})`
- **THEN** the ToolGovernancePolicy SHALL validate the invocation
- **AND** the SimilarCaseAgent pipeline SHALL execute and return results
- **AND** the invocation SHALL be logged in the tool audit log.

---

### Requirement: Cross-Agent Collaboration

Agents SHALL be able to invoke other Agents during execution to compose multi-domain results.

#### Scenario: Contract review agent calls similar case agent

- **WHEN** the ContractReviewExecutor detects dispute focus points in a contract
- **THEN** it MAY invoke the `similar_case_search` tool to find supporting precedents
- **AND** the similar case results SHALL be incorporated into the contract review output.

#### Scenario: Opponent prediction agent calls retrieval tool

- **WHEN** the PredictionExecutor needs supporting evidence for predicted arguments
- **THEN** it MAY invoke the `grounded_chat` or `retrieval` tool to gather evidence
- **AND** the evidence SHALL be cited in the prediction report.

#### Scenario: Agent invokes multiple tools in sequence

- **WHEN** an Agent needs results from two different tools (e.g., retrieval + similar_case)
- **THEN** the Agent SHALL invoke each tool sequentially via `invoke_tool()`
- **AND** each invocation SHALL be independently governed and logged.

---

### Requirement: Recursion Depth Limit

The system SHALL enforce a maximum recursion depth for Agent-to-Agent calls to prevent infinite loops.

The default maximum depth SHALL be 3. This limit SHALL be enforced by the ToolGovernancePolicy and SHALL NOT be overridable by Agent output.

#### Scenario: Recursion within limit succeeds

- **WHEN** Agent A invokes Agent B (depth=1), and Agent B invokes Agent C (depth=2)
- **AND** the maximum depth is 3
- **THEN** all invocations SHALL succeed normally.

#### Scenario: Recursion exceeds limit is blocked

- **WHEN** Agent A invokes Agent B (depth=2), and Agent B attempts to invoke Agent A again (depth=3)
- **AND** the maximum depth is 3
- **THEN** the ToolGovernancePolicy SHALL block the invocation
- **AND** an audit event SHALL be logged with reason=`recursion_depth_exceeded`.

#### Scenario: Recursion depth tracked per request

- **WHEN** an Agent-to-Agent call is initiated
- **THEN** the current recursion depth SHALL be passed as context metadata
- **AND** the depth counter SHALL increment by 1 for each nested call.

---

### Requirement: Agent-to-Agent Call Governance

Every Agent-to-Agent call SHALL pass through the full governance pipeline: ToolGovernancePolicy (permission check + schema validation) + OutputGovernancePipeline (content safety).

#### Scenario: Agent-to-Agent call governed by tool policy

- **WHEN** an Agent invokes another Agent via `invoke_tool()`
- **THEN** the ToolGovernancePolicy SHALL validate the tool is registered, the caller has permission, and the arguments are schema-valid
- **AND** only after all checks pass SHALL the target Agent execute.

#### Scenario: Agent-to-Agent output governed by output pipeline

- **WHEN** a target Agent returns results to the calling Agent
- **THEN** the OutputGovernancePipeline SHALL validate the output before it is returned to the caller
- **AND** if governance fails, the calling Agent SHALL receive an error, not the raw output.
