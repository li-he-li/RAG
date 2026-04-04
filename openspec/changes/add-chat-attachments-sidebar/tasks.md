## 1. Ordinary Chat Attachment Flow

- [x] 1.1 Extend the frontend session model with ordinary chat attachment state and right-sidebar tab state
- [x] 1.2 Route the shared composer upload button to ordinary chat attachments in ordinary mode and review-target uploads in contract review mode
- [x] 1.3 Add frontend ordinary chat attachment upload, removal, and upload feedback interactions
- [ ] 1.4 Add a shared session-temp file backend capability (upload/list/delete + session cleanup) for `chat_attachment` and `review_target`, and keep it outside the database, vector index, and template library
- [ ] 1.5 Pass current-session ordinary chat attachments into the main chat request flow so assistant answers can read them

## 2. Right Sidebar Tabs

- [x] 2.1 Replace the single-purpose citation sidebar with a tabbed right sidebar that supports attachments and citations
- [x] 2.2 Render the current session's ordinary chat attachments in the attachments tab
- [x] 2.3 Keep citation-trigger behavior working by automatically switching the sidebar to the citations tab when needed

## 3. Verification and Boundaries

- [ ] 3.1 Verify ordinary chat attachments never appear in the persistent document management list or standard template library
- [ ] 3.2 Verify ordinary chat attachments are cleared when the current session is reset or replaced
- [ ] 3.3 Verify the shared upload button routes to the correct flow in ordinary chat mode versus contract review mode
- [ ] 3.4 Verify assistant answers can read ordinary chat attachments and the right sidebar can switch between attachments and citations

## 4. Cross-Change Coordination

- [ ] 4.1 Expose the shared session-temp file contract for `add-contract-review-chat-mode` to reuse instead of building a second temporary upload path
