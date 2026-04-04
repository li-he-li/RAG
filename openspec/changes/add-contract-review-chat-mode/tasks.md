## 1. Frontend Chat Mode Integration

- [x] 1.1 Remove the existing helper text above the composer without changing unrelated chat layout
- [x] 1.2 Add a contract review mode toggle below the composer and persist its state per chat session
- [x] 1.3 Add a left-side upload button to the composer for review-target contract files
- [x] 1.4 Add temporary review file state, recommended template state, and selected template state to the frontend session model
- [x] 1.5 Allow contract review submission without uploaded contracts and return an explicit no-contract-review result

## 2. Template Library Panel

- [x] 2.1 Replace the current contract review placeholder panel with a standard template management panel
- [x] 2.2 Implement standard template upload, list, and delete interactions in the left-side contract review panel
- [x] 2.3 Ensure template library items remain separate from the existing temporary review upload flow

## 3. Backend Contract Review Flow

- [ ] 3.1 Reuse the shared session-temp file backend capability from `add-chat-attachments-sidebar` for `review_target` uploads instead of adding a separate temporary upload endpoint
- [ ] 3.2 Wire contract review flow to the shared session cleanup lifecycle so `review_target` files are removed when the session is reset or replaced
- [ ] 3.3 Add template recommendation logic that returns a recommended template plus candidate templates for uploaded contracts
- [ ] 3.4 Add a streamed contract review endpoint that accepts temporary review files and a selected standard template
- [ ] 3.5 Implement template-difference review generation that compares each uploaded contract against the selected standard template
- [ ] 3.6 Stream multiple contract review results serially in file order through the main chat response channel

## 4. Verification and Safeguards

- [ ] 4.1 Verify ordinary chat mode still works unchanged after adding contract review mode
- [ ] 4.2 Verify temporary review-target contracts never appear in persistent document or template listings
- [ ] 4.3 Verify users can override the recommended template before starting review
- [ ] 4.4 Verify session reset or replacement clears temporary review-target contracts
- [ ] 4.5 Validate no-contract handling, multi-file contract review, parsing failure handling, and serial streaming output
