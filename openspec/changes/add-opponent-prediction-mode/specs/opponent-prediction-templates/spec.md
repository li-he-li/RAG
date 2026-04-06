## ADDED Requirements

### Requirement: Prediction Template Management Page
The system SHALL provide a dedicated left-side prediction template management page for creating, listing, and deleting reusable case templates.

#### Scenario: User opens prediction template management
- **WHEN** the user clicks the `观点预测` entry in the left navigation
- **THEN** the system shows a template management page instead of directly starting a prediction task

### Requirement: Case Template Requires Case Name and Case Materials
The system SHALL require each prediction template to include a case name and at least one case material before the template can be saved.

#### Scenario: User tries to save without case name
- **WHEN** the user attempts to save a template with an empty case name
- **THEN** the system MUST reject the save and indicate that the case name is required

#### Scenario: User tries to save without case materials
- **WHEN** the user attempts to save a template without any uploaded case material
- **THEN** the system MUST reject the save and indicate that case material is required

### Requirement: Opponent Corpus Is Optional
The system SHALL allow a prediction template to be saved even when no opponent corpus has been uploaded.

#### Scenario: User saves template without opponent corpus
- **WHEN** the user provides a case name and at least one case material but no opponent corpus
- **THEN** the system saves the template successfully

### Requirement: Saved Templates Are Reusable and Listed
The system SHALL persist saved prediction templates and list them in the prediction template management page for later reuse.

#### Scenario: Saved template appears in management list
- **WHEN** the user successfully saves a prediction template
- **THEN** the system shows that template in the page list with its case name and material counts

### Requirement: Template Materials Stay in Prediction Domain Storage
The system SHALL store prediction template materials in dedicated prediction-domain persistence and MUST NOT place them into the ordinary document management list, template library, or main retrieval document store.

#### Scenario: Prediction template material does not appear in other persistent lists
- **WHEN** the user uploads case material or opponent corpus for a prediction template
- **THEN** that material does not appear in the ordinary file management list or contract template library

### Requirement: Template Deletion Uses Hard Delete
The system SHALL hard-delete a prediction template and all of its associated materials and derived records when the user deletes that template.

#### Scenario: User deletes a saved template
- **WHEN** the user deletes a prediction template from the management page
- **THEN** the system removes the template, its materials, and its derived prediction-domain records from persistence
