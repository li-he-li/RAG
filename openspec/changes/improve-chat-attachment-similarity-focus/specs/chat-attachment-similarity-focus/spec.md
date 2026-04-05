## ADDED Requirements

### Requirement: Attachment Focus Selection Must Be Query-Aware
The system SHALL select retrieval input from a session chat attachment based on the current user query instead of taking only the beginning of the file.

#### Scenario: Long attachment with key facts in later sections
- **WHEN** a normal-mode chat request uses a long uploaded case attachment
- **THEN** the system evaluates attachment chunks against the user query and chooses the most relevant chunks as attachment retrieval input

### Requirement: Attachment Processing Must Stay Temporary
The system SHALL NOT persist user-uploaded chat attachment chunks or their derived retrieval focus into the permanent document database or vector index.

#### Scenario: Attachment-driven retrieval request executes
- **WHEN** the system performs query-aware attachment focus selection
- **THEN** all chunking and scoring occur in request/session runtime only without ingesting the attachment into persistent search storage

### Requirement: Attachment Focus Retrieval Must Preserve Fallback Behavior
The system SHALL fall back to query-only retrieval when attachment focus selection cannot produce usable attachment content.

#### Scenario: Unusable attachment content
- **WHEN** the latest chat attachment exists but its focused chunk selection fails or returns no usable text
- **THEN** the system performs normal query-only retrieval without failing the response

### Requirement: DeepSeek Similarity Reasoning Must Use Focused Attachment Context
When attachment-driven retrieval is used, the system SHALL provide DeepSeek with focused attachment context derived from the uploaded case rather than a naive leading excerpt.

#### Scenario: Similar-case explanation with attachment context
- **WHEN** the system generates a grounded answer for a request that used attachment focus selection
- **THEN** the prompt includes the attachment file identity and focused attachment context that reflects query-relevant sections of the uploaded case
