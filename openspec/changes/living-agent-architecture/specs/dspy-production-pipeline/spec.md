# DSPy Production Pipeline

## ADDED Requirements

### Requirement: Trajectory Export to DSPy Examples

The system SHALL provide an API endpoint that exports TrajectoryStore records as DSPy-compatible Example sets for prompt optimization.

The export SHALL use `export_trajectory_evalset()` from `app.prompts.optimization`.

#### Scenario: Export trajectory data for a prompt

- **WHEN** an admin calls `POST /api/admin/export-dspy-dataset` with `prompt_name="chat"` and `input_keys=("query",)`
- **THEN** the system SHALL read trajectory records from TrajectoryStore
- **AND** filter records where `prompt_versions` contains the specified prompt_name
- **AND** return a JSON array of DSPy Example objects with input/output fields.

#### Scenario: Empty trajectory returns empty dataset

- **WHEN** no trajectory records exist for the specified prompt_name
- **THEN** the endpoint SHALL return an empty array
- **AND** no error SHALL be raised.

---

### Requirement: Prompt Optimization Trigger

The system SHALL provide an API endpoint that triggers DSPy prompt optimization on demand.

The endpoint SHALL call `optimize_prompt_module()` with the exported dataset and return the optimization result.

#### Scenario: Successful optimization run

- **WHEN** an admin calls `POST /api/admin/optimize-prompt` with `prompt_name="chat"` and sufficient trajectory data
- **THEN** the system SHALL: (1) export trajectory data, (2) create optimization module, (3) run BootstrapFewShot optimizer, (4) return the validation score and compiled status
- **AND** the response SHALL include `validation_score` and `compiled` boolean.

#### Scenario: Insufficient data for optimization

- **WHEN** the exported dataset has fewer than 3 examples
- **THEN** the endpoint SHALL return HTTP 422 with a message indicating insufficient data
- **AND** no optimization SHALL be attempted.

---

### Requirement: Optimized Prompt Variant Registration

After a successful optimization run, the system SHALL register the optimized prompt as a versioned variant in PromptRegistry.

The variant SHALL be registered with a version suffix like `v1-optimized-{timestamp}`.

#### Scenario: Optimized variant registered

- **WHEN** an optimization run completes with `compiled=True`
- **THEN** the system SHALL register the compiled prompt as a new variant in PromptRegistry
- **AND** the variant name SHALL be `{prompt_name}-optimized`
- **AND** the variant SHALL be discoverable via the PromptRegistry API.

#### Scenario: Variant available for rendering

- **WHEN** a subsequent request asks to render the optimized variant
- **THEN** PromptRegistry SHALL return the optimized prompt template
- **AND** the optimized prompt SHALL include few-shot examples from the Bootstrap process.

---

### Requirement: A/B Prompt Variant Endpoint

The system SHALL provide an API endpoint to list and compare baseline vs optimized prompt variants.

#### Scenario: List all variants for a prompt

- **WHEN** an admin calls `GET /api/admin/prompt-variants/{prompt_name}`
- **THEN** the endpoint SHALL return both the baseline and any optimized variants
- **AND** each variant SHALL include version, creation time, and optimization score (if applicable).

#### Scenario: Activate optimized variant

- **WHEN** an admin calls `PUT /api/admin/prompt-variants/{prompt_name}/activate` with a variant version
- **THEN** the PromptRegistry SHALL use the specified variant for all subsequent renderings of that prompt
- **AND** the change SHALL take effect immediately (hot-reload).

---

### Requirement: Trajectory Logging for All Agent Pipelines

Every AgentPipeline execution SHALL log trajectory records that include the prompt version used, enabling future optimization.

#### Scenario: Trajectory includes prompt version

- **WHEN** a Chat pipeline execution completes
- **THEN** the trajectory record SHALL include `prompt_versions={"chat": "v1.2"}`
- **AND** this data SHALL be queryable for DSPy dataset export.

#### Scenario: Trajectory includes input and output

- **WHEN** any pipeline execution completes
- **THEN** the trajectory record SHALL include the input data and output data
- **AND** the data SHALL be structured for `export_trajectory_evalset()` to parse.
