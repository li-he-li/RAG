## ADDED Requirements

### Requirement: Dual-Layer Similarity Retrieval
The system SHALL support dual-layer retrieval for legal search, including document-level similarity for whole-case matching and paragraph-level similarity for evidence localization.

#### Scenario: Query returns document and paragraph matches
- **WHEN** a user submits a similarity search query
- **THEN** the system returns ranked document-level matches and paragraph-level evidence matches within those documents

### Requirement: Dispute-Focused Paragraph Matching
The system SHALL prioritize paragraph-level matching around dispute-focus semantics, not only general lexical overlap.

#### Scenario: Dispute-focused segments are ranked first
- **WHEN** the query contains a specific dispute focus
- **THEN** the system ranks paragraphs aligned with that dispute focus ahead of unrelated but lexically similar paragraphs

### Requirement: Hierarchical Evidence Identifiers
The system SHALL maintain hierarchical identifiers where each document has a stable `doc_id` and each paragraph has a stable `para_id` linked to its parent `doc_id`.

#### Scenario: Paragraph can be traced to parent document
- **WHEN** a paragraph-level hit is returned
- **THEN** the response includes both `para_id` and parent `doc_id`

### Requirement: Verifiable Citation Metadata
The system SHALL return verifiable citation metadata for each paragraph-level hit, including `file_name`, `line_start`, `line_end`, and `version_id`.

#### Scenario: User verifies citation against source
- **WHEN** the user inspects a paragraph-level match
- **THEN** the system provides file name and line range that can be used to locate the source evidence in the referenced version

### Requirement: Evidence Snippet and Match Explanation
The system SHALL provide an evidence snippet and a human-readable match explanation for each paragraph-level hit.

#### Scenario: User understands why a hit was returned
- **WHEN** search results are displayed
- **THEN** each paragraph-level result includes an evidence excerpt and explanation tied to case similarity or dispute-focus similarity

### Requirement: Stable Frontend Retrieval Contract
The system SHALL expose a stable retrieval contract that can be integrated as a core capability in the unified web frontend.

#### Scenario: Frontend consumes unified response structure
- **WHEN** the web frontend calls the similarity search API
- **THEN** it receives a consistent response schema containing document-level ranking and nested paragraph-level evidence details

### Requirement: Grounded DeepSeek Dialogue Over Indexed Evidence
The system SHALL support DeepSeek dialogue that is grounded in indexed database evidence and provides verifiable citations.

#### Scenario: User asks question in chat and receives grounded answer
- **WHEN** the user submits a chat question from the web frontend
- **THEN** the system retrieves relevant evidence from indexed documents and returns a DeepSeek answer plus citations

#### Scenario: Chat answer includes citation metadata for verification
- **WHEN** the system returns a chat answer
- **THEN** each cited evidence item includes `file_name`, `line_start`, `line_end`, and `version_id`

### Requirement: Automatic Dependency Bootstrap
The system MUST automatically download and prepare required runtime dependencies, including PostgreSQL, Qdrant, BAAI/bge-m3, and bge-reranker-v2-m3, during initialization.

#### Scenario: First-time initialization
- **WHEN** the system is started in a clean environment without required dependencies
- **THEN** it automatically downloads and prepares the required database components and embedding/reranker models before enabling retrieval services

#### Scenario: Initialization failure handling
- **WHEN** automatic dependency bootstrap fails due to network or permission issues
- **THEN** the system reports clear actionable errors and keeps retrieval services unavailable until bootstrap succeeds
