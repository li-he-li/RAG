## ADDED Requirements

### Requirement: Ordinary Chat Supports Session Attachments
The system SHALL allow users in ordinary chat mode to upload one or more files as session-scoped chat attachments from the main chat composer.

#### Scenario: User uploads attachments in ordinary chat mode
- **WHEN** the user uploads files while the main composer is in ordinary chat mode
- **THEN** the system associates those files with the current chat session as ordinary chat attachments

### Requirement: Chat Attachments Are Readable by the Main Chat
The system SHALL make ordinary chat attachments available to the main chat response flow as readable input context for the current session.

#### Scenario: Assistant answer uses uploaded attachment content
- **WHEN** the user sends a normal chat request after uploading one or more ordinary chat attachments
- **THEN** the chat response flow can read those attachments as part of the answer context

### Requirement: Chat Attachments Stay Outside Persistent Knowledge Storage
The system SHALL keep ordinary chat attachments outside the database, vector index, template library, and file management list.

#### Scenario: Ordinary chat attachment does not appear in persistent lists
- **WHEN** a file is uploaded as an ordinary chat attachment
- **THEN** that file does not appear in the persistent document management list or standard template library

### Requirement: Ordinary Chat Attachments Are Session Scoped
The system SHALL remove ordinary chat attachments when the current chat session is cleared, replaced, or otherwise terminated.

#### Scenario: Session reset clears ordinary chat attachments
- **WHEN** the current chat session is cleared or replaced
- **THEN** the system removes the session's ordinary chat attachments and they are no longer available to later chat requests

### Requirement: Composer Upload Routing Is Mode Aware
The system SHALL route the shared composer upload control to the ordinary chat attachment flow in ordinary mode and to the review-target contract flow in contract review mode.

#### Scenario: Shared upload button routes by current mode
- **WHEN** the user presses the left-side upload control in the composer
- **THEN** the system selects the upload path that matches the current composer mode
