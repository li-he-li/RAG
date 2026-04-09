# Prompt Registry

## ADDED Requirements

### Requirement: PromptRegistry YAML Loading

The system SHALL provide a `PromptRegistry` that loads YAML prompt templates from the `backend/app/prompts/` directory.

Each YAML file in the prompts directory MUST define at least one prompt template. The registry SHALL load all templates at application startup and make them available for lookup by name.

#### Scenario: Registry loads prompts from YAML files

WHEN the application starts
THEN `PromptRegistry` SHALL scan the `backend/app/prompts/` directory for `.yaml` and `.yml` files
AND parse each file into prompt template objects.

#### Scenario: Registry skips invalid YAML files

WHEN a YAML file contains syntax errors or missing required fields
THEN the registry SHALL log a warning with the filename and error details
AND continue loading remaining files without crashing.

#### Scenario: Registry handles empty prompts directory

WHEN the `backend/app/prompts/` directory is empty or does not exist
THEN the registry SHALL initialize with zero templates
AND log an informational message indicating no prompts were loaded.

---

### Requirement: Prompt Template Schema

Each prompt template loaded by the registry SHALL conform to the following schema:
- `name` — unique string identifier for the prompt
- `version` — semantic version string (e.g., "1.2.0")
- `segments` — list of message segments, each with a `role` (system/user/assistant) and `content` string
- `variables` — list of variable names that the template expects

#### Scenario: Template with all required fields

WHEN a YAML file contains name, version, segments, and variables
THEN the registry SHALL parse it into a valid `PromptTemplate` object
AND the template SHALL be available for lookup by name.

#### Scenario: Template missing required fields

WHEN a YAML file is missing the `name` or `segments` field
THEN the registry SHALL reject the template
AND log an error indicating which required field is missing.

#### Scenario: Template segments are ordered

WHEN a template has multiple segments
THEN the segments SHALL be stored and returned in the order defined in the YAML file
AND the order MUST be preserved when the prompt is sent to the LLM.

---

### Requirement: Hot-Reload on File Changes

The `PromptRegistry` SHALL detect changes to prompt template files and reload them without requiring an application restart.

The registry MUST use a file watcher to monitor the prompts directory for modifications, creations, and deletions.

#### Scenario: Registry detects modified prompt file

WHEN a YAML prompt file is modified on disk
THEN the registry SHALL reload that file within 5 seconds
AND the updated template SHALL be available for subsequent requests without restart.

#### Scenario: Registry detects new prompt file

WHEN a new YAML file is added to the prompts directory
THEN the registry SHALL detect and load it within 5 seconds
AND the new prompt SHALL be available for lookup by name.

#### Scenario: Registry detects deleted prompt file

WHEN a YAML file is removed from the prompts directory
THEN the registry SHALL remove the corresponding template from the active registry
AND subsequent lookups for that name SHALL raise `PromptNotFoundError`.

---

### Requirement: DSPy Integration

Each prompt template in the registry SHALL be wrappable as a DSPy Signature for structured LLM calls.

The registry MUST provide a method to convert a prompt template into a DSPy-compatible Signature class that can be used with DSPy modules.

#### Scenario: Convert prompt to DSPy Signature

WHEN `PromptRegistry.to_dspy_signature("prompt_name")` is called
THEN it SHALL return a DSPy Signature class
AND the Signature MUST have input fields matching the template's variables and an output field for the LLM response.

#### Scenario: DSPy Signature preserves segment structure

WHEN a DSPy Signature derived from a prompt template is used to make an LLM call
THEN the system prompt and user prompt segments SHALL be composed in the correct order
AND the variable substitution MUST be applied before the call.

---

### Requirement: Version Tracking

The `PromptRegistry` SHALL track version numbers for all prompt templates and log version changes.

Every modification to a prompt template MUST be recorded with the new version number and timestamp.

#### Scenario: Version recorded on load

WHEN the registry loads a prompt template with version "1.0.0"
THEN the version SHALL be stored alongside the template
AND available via `PromptRegistry.get_version("prompt_name")`.

#### Scenario: Version change detected on reload

WHEN a prompt file is modified and the version field changes from "1.0.0" to "1.1.0"
THEN the registry SHALL log a version change event with the old version, new version, and timestamp
AND the active template SHALL be updated to the new version.

#### Scenario: Version unchanged on reload

WHEN a prompt file is modified but the version field remains the same
THEN the registry SHALL log a warning that the content changed but the version was not bumped
AND still apply the updated content.

---

### Requirement: Variable Substitution

The `PromptRegistry` SHALL support `{{variable}}` syntax for runtime variable substitution in prompt content.

All occurrences of `{{variable_name}}` in segment content MUST be replaced with the provided value when the prompt is rendered.

#### Scenario: Single variable substitution

WHEN a prompt segment contains `"Analyze this case: {{case_description}}"` and the variable `case_description` is provided as "contract dispute"
THEN the rendered segment SHALL contain `"Analyze this case: contract dispute"`.

#### Scenario: Multiple variables in one segment

WHEN a prompt segment contains `"{{party_a}} vs {{party_b}}"` with variables `party_a="Alice"` and `party_b="Bob"`
THEN the rendered segment SHALL contain `"Alice vs Bob"`.

#### Scenario: Missing variable raises error

WHEN a prompt is rendered but a required variable is not provided
THEN the registry SHALL raise a `PromptVariableError` with the name of the missing variable
AND the prompt SHALL NOT be sent to the LLM with unresolved placeholders.

#### Scenario: Extra variables are ignored

WHEN more variables are provided than the template references
THEN the registry SHALL render the prompt using only the referenced variables
AND log a debug message noting the unused variables.
