## ADDED Requirements

### Requirement: Normal Chat Retrieval Can Use Session Chat Attachment Content
The system SHALL allow normal-mode chat retrieval to use session-scoped `chat_attachment` content as retrieval input when attachment mode is enabled for the request.

#### Scenario: Attachment-driven retrieval executes
- **WHEN** a normal-mode chat request includes `session_id` and attachment mode is enabled, and at least one usable `chat_attachment` exists
- **THEN** the retrieval pipeline uses attachment content together with user query text to construct retrieval input

### Requirement: Auto-Prioritize Latest Chat Attachment
The system SHALL select the most recently uploaded and not deleted `chat_attachment` as the retrieval source when multiple chat attachments exist in the same session.

#### Scenario: Multiple chat attachments in one session
- **WHEN** a normal-mode chat request is processed with attachment mode enabled and multiple chat attachments are present
- **THEN** the latest available chat attachment is selected as the attachment retrieval source

### Requirement: Attachment-Aware Retrieval Is Backward Compatible
The system SHALL keep existing query-only retrieval behavior for clients that do not send attachment context fields or when no usable chat attachment is available.

#### Scenario: Legacy client request
- **WHEN** a normal-mode chat request omits `session_id` or attachment mode is disabled
- **THEN** the system performs query-only retrieval with existing behavior

#### Scenario: Missing or unusable attachment
- **WHEN** attachment mode is enabled but no usable chat attachment can be resolved for the request
- **THEN** the system falls back to query-only retrieval without failing the chat response

### Requirement: Chat Response Indicates Attachment Retrieval Usage
The system SHALL expose whether attachment-driven retrieval was used and SHALL identify the source attachment filename in response metadata when available.

#### Scenario: Attachment used in retrieval
- **WHEN** normal-mode retrieval uses a chat attachment as source
- **THEN** response metadata includes an attachment-used indicator and the attachment filename

#### Scenario: Attachment not used
- **WHEN** normal-mode retrieval runs in query-only mode
- **THEN** response metadata indicates attachment mode was not used

### Requirement: Frontend Shows Attachment-Usage Notice in Main Chat
The frontend SHALL display an explicit notice in the main chat response when backend metadata reports that attachment-driven retrieval was used.

#### Scenario: Main chat displays attachment source notice
- **WHEN** the chat stream result reports attachment usage metadata
- **THEN** the main chat response shows a notice identifying the attachment source file used for retrieval
