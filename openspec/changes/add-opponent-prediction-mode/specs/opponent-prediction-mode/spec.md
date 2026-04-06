## ADDED Requirements

### Requirement: Prediction Mode in Main Chat
The system SHALL provide a dedicated opponent-prediction mode inside the main chat composer alongside the existing ordinary chat and contract review modes.

#### Scenario: User enters prediction mode
- **WHEN** the user activates the `观点预测` control in the chat composer
- **THEN** the current chat session enters opponent-prediction mode and the control is visually highlighted

### Requirement: Prediction Requests Require Natural Language Query and Selected Template
The system SHALL require the user to provide both a natural language query and a selected prediction template before a prediction request can be executed.

#### Scenario: User attempts prediction without query
- **WHEN** the user is in opponent-prediction mode and submits an empty message
- **THEN** the system MUST reject the request and not start prediction

#### Scenario: User attempts prediction without template selection
- **WHEN** the user is in opponent-prediction mode and submits a message without selecting a prediction template
- **THEN** the system MUST reject the request and indicate that a template must be selected

### Requirement: Prediction Uses Query and Selected Template Together
The system SHALL construct the prediction input from the user's natural language query and the currently selected prediction template.

#### Scenario: System starts prediction with combined inputs
- **WHEN** the user submits a prediction request with a query and a selected template
- **THEN** the system starts the prediction flow using both the query and the selected template's saved materials

### Requirement: Prediction Generates Structured Opponent Argument Analysis
The system SHALL generate a structured prediction result that includes likely opponent arguments, supporting basis, and counter-strategy guidance instead of returning only a plain free-form answer.

#### Scenario: Prediction output includes opponent arguments and counter guidance
- **WHEN** a prediction request completes successfully
- **THEN** the system returns a structured result containing likely opponent viewpoints and corresponding response guidance

### Requirement: Prediction Results Are Rendered as a Report Card
The system SHALL render completed prediction results in the main chat area as a dedicated prediction report card.

#### Scenario: Completed prediction appears as report card
- **WHEN** the prediction flow returns a result
- **THEN** the main chat area shows a dedicated prediction report card rather than a plain chat message only

### Requirement: Prediction Results Distinguish Evidence from Inference
The system SHALL distinguish evidence-supported points from inference-only points in the prediction result.

#### Scenario: Result contains inference-only point
- **WHEN** the system cannot attach supporting citation evidence to part of the prediction
- **THEN** that part of the result is marked as inference rather than presented as cited evidence

### Requirement: Deleted Selected Template Invalidates Prediction Submission
The system SHALL clear the current prediction template selection and block further prediction submissions if the selected template is deleted.

#### Scenario: Currently selected template is deleted
- **WHEN** the template currently selected in opponent-prediction mode is deleted
- **THEN** the system clears the selection and prevents new prediction requests until another template is selected
