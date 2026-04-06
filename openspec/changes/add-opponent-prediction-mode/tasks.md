## 1. Prediction Domain Data Model

- [x] 1.1 Add database tables and backend schemas for prediction templates, template assets, asset paragraphs, and optional report snapshots
- [x] 1.2 Reuse the existing document parsing pipeline to extract normalized text and paragraph records for prediction template materials without writing them into the main document store
- [x] 1.3 Implement hard-delete cleanup that removes a prediction template together with its materials, derived paragraph rows, and stored report snapshots

## 2. Template Management APIs

- [x] 2.1 Add API endpoints to create, list, inspect, and delete prediction templates
- [x] 2.2 Add API endpoints to upload and delete template assets for `case_material` and optional `opponent_corpus`
- [x] 2.3 Enforce save-time validation so templates require `case_name` and at least one `case_material`

## 3. Frontend Template Management Page

- [x] 3.1 Add the left navigation entry and panel for `观点预测` template management
- [x] 3.2 Implement case name input, case material upload, optional opponent corpus upload, and template save interactions
- [x] 3.3 Render the saved template list at the bottom of the page with case name, material counts, updated time, and delete actions
- [x] 3.4 Ensure the left-side page remains a management page only and does not start prediction directly

## 4. Chat Mode Integration

- [x] 4.1 Add an `opponent-prediction` mode toggle to the main composer alongside ordinary chat and contract review
- [x] 4.2 Add a template selector in the chat area that is shown in prediction mode and supports choosing exactly one saved prediction template
- [x] 4.3 Require both a non-empty natural language query and a selected template before submitting a prediction request
- [x] 4.4 Clear the current selection and block further submissions if the selected template is deleted

## 5. Backend Prediction Flow

- [x] 5.1 Add a prediction start endpoint that accepts `session_id`, `template_id`, and `query`
- [x] 5.2 Implement case profile extraction from the selected template materials and the user's natural language request
- [x] 5.3 Implement opponent-side retrieval that reuses existing retrieval and citation foundations to gather support for likely opponent viewpoints
- [x] 5.4 Implement viewpoint-tree generation and per-viewpoint counter-strategy generation
- [x] 5.5 Return structured prediction results as a report object suitable for a dedicated chat report card

## 6. Rendering and Verification

- [x] 6.1 Render prediction results in the main chat stream as a dedicated prediction report card with case summary, predicted viewpoints, citations, and counter guidance
- [x] 6.2 Mark inference-only content distinctly from citation-supported content in the rendered result
- [x] 6.3 Verify ordinary chat and contract review flows remain unchanged after adding prediction mode
- [x] 6.4 Verify multi-template scenarios, required-field validation, hard-delete cleanup, and deleted-selection handling
