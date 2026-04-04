## ADDED Requirements

### Requirement: Contract Review Mode in Main Chat
The system SHALL provide a dedicated contract review mode inside the main chat composer instead of requiring users to start review work from a separate primary page.

#### Scenario: User enters contract review mode
- **WHEN** the user activates the contract review control in the chat composer
- **THEN** the current chat session enters contract review mode and the control is visually highlighted

### Requirement: Temporary Review File Upload
The system SHALL allow users in contract review mode to upload one or more review-target contract files as temporary session-scoped inputs.

#### Scenario: User uploads review files
- **WHEN** the user uploads contract files while contract review mode is active
- **THEN** the system associates those files with the current session for review use only

#### Scenario: Temporary review files stay outside persistent knowledge storage
- **WHEN** a review-target contract file is uploaded for contract review
- **THEN** the system MUST NOT persist that file into the database, vector index, or document management list

### Requirement: Session-Scoped Review File Lifetime
The system SHALL keep uploaded review-target files available only within the current chat session lifecycle.

#### Scenario: Session ends or is reset
- **WHEN** the current session is cleared, replaced, or otherwise terminated
- **THEN** the system removes the temporary review-target files and they are no longer available for contract review

### Requirement: Template Recommendation with Manual Override
The system SHALL recommend a standard template for each uploaded review-target contract and SHALL allow the user to override that recommendation before review execution.

#### Scenario: System recommends a template
- **WHEN** the user uploads a review-target contract
- **THEN** the system returns a recommended standard template and a list of selectable template candidates

#### Scenario: User overrides the recommended template
- **WHEN** the user selects a different standard template before starting review
- **THEN** the system uses the user-selected template instead of the recommendation

### Requirement: Review Requests Handle Missing Uploaded Contracts Explicitly
The system SHALL accept a contract review request even when no uploaded review-target contract is present and SHALL return a clear no-contract-review result instead of silently proceeding.

#### Scenario: Review request without uploaded file returns explicit empty result
- **WHEN** the user submits a contract review request without any uploaded review-target contract
- **THEN** the system returns a clear response that there is currently no contract available for review

### Requirement: Template-Difference Review Output
The system SHALL generate contract review output by comparing each uploaded review-target contract with a selected standard template and SHALL focus the first version of review results on template differences.

#### Scenario: Review result focuses on template differences
- **WHEN** a contract review request is executed
- **THEN** the returned answer highlights missing clauses, deviations from the standard template, or suggested corrections derived from the template comparison

### Requirement: Serial Streaming Results for Multiple Contracts
The system SHALL support multiple uploaded review-target contracts in one request and SHALL stream the review results into the main chat window in file-by-file sequence.

#### Scenario: Multiple uploaded files are reviewed in order
- **WHEN** the user submits a contract review request with multiple uploaded files
- **THEN** the system streams review output for those files serially instead of interleaving the content
