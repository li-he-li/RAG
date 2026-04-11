# Governance Pipeline (Modified)

## MODIFIED Requirements

### Requirement: Non-Bypassable Governance

The governance pipeline SHALL be non-bypassable: it MUST run in the application layer and the LLM model SHALL NOT be able to skip it.

No code path from agent output to HTTP response SHALL bypass the governance pipeline.

This requirement is extended to cover Agent-to-Agent calls: governance SHALL also apply to outputs returned from one Agent to another within the system.

#### Scenario: Governance cannot be skipped by agent

- **WHEN** any agent in the pipeline attempts to return output directly to the HTTP response
- **THEN** the framework SHALL route the output through the governance pipeline first
- **AND** there SHALL be no API or method to disable governance for individual requests.

#### Scenario: Governance applies to Agent-to-Agent calls

- **WHEN** Agent A invokes Agent B via `invoke_tool()`
- **THEN** Agent B's output SHALL pass through the OutputGovernancePipeline before being returned to Agent A
- **AND** if governance blocks the output, Agent A SHALL receive a `GovernanceBlockError`, not the raw output.

#### Scenario: Governance is enforced for all response paths

- **WHEN** a response is returned via streaming, synchronous return, Agent-to-Agent call, or error recovery
- **THEN** governance checks SHALL apply to all paths equally.
