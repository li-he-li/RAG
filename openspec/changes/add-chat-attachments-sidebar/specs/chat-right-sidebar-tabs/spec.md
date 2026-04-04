## ADDED Requirements

### Requirement: Right Sidebar Provides Top-Level Tabs
The system SHALL provide top-level tabs in the chat right sidebar so users can switch between at least an attachments view and a citations view.

#### Scenario: User switches right sidebar tabs
- **WHEN** the right sidebar is open and the user selects a different top-level tab
- **THEN** the sidebar updates to show the content for the selected tab

### Requirement: Sidebar Shows Current Session Attachments
The system SHALL show the current session's ordinary chat attachments inside the attachments tab of the right sidebar.

#### Scenario: Uploaded attachment appears in attachments tab
- **WHEN** the user uploads an ordinary chat attachment
- **THEN** the attachments tab lists that attachment for the current session

### Requirement: Citations Remain Available Within the Tabbed Sidebar
The system SHALL preserve citation browsing inside the citations tab after the sidebar is converted to a tabbed layout.

#### Scenario: Citation trigger opens citations tab
- **WHEN** the user clicks a citation trigger from a chat response
- **THEN** the right sidebar opens on the citations tab and shows the selected citation content
