## Why

In normal chat mode, uploaded case files are currently only UI-level attachments and are not used by the similar-case retrieval pipeline.  
This creates a mismatch between user intent ("find similar cases based on my uploaded case") and actual behavior, so we need to make chat attachments first-class retrieval input now.

## What Changes

- Extend normal chat retrieval requests to include session context so backend can resolve current chat attachments.
- Add attachment-aware query construction in the retrieval/chat pipeline:
  - Auto-prioritize the latest chat attachment in the active session.
  - Combine attachment content with user query to drive similar-case retrieval.
  - Fall back to current query-only retrieval when no usable attachment exists.
- Add response metadata indicating whether attachment-driven retrieval was used and which file was applied.
- Update frontend chat rendering to show an explicit notice when retrieval used an attachment source.
- Keep contract-review flow unchanged and isolated.

## Capabilities

### New Capabilities
- `chat-attachment-driven-retrieval`: Use normal-mode session chat attachments as retrieval input for similar-case search and grounded chat responses.

### Modified Capabilities
- None.

## Impact

- Affected frontend: normal-mode submit payload and chat result rendering in `frontend/app.js`.
- Affected backend API/types: `ChatRequest` schema and `/api/chat`, `/api/chat/stream` handling.
- Affected backend services: retrieval/query building path in grounded chat execution.
- No new infrastructure dependencies; reuses existing session temp file store and `chat_attachment` kind.
