## 1. Attachment Focus Helper

- [x] 1.1 Add a backend helper to segment uploaded attachment text into candidate chunks/windows using the existing parser.
- [x] 1.2 Score chunks against the current user query and return top focused chunks plus a compact focus summary.
- [x] 1.3 Keep helper output bounded so retrieval and prompting remain stable for large files.

## 2. Chat Retrieval Integration

- [x] 2.1 Replace current front-truncation logic in `backend/app/services/chat.py` with query-aware attachment focus selection.
- [x] 2.2 Keep latest-chat-attachment selection policy unchanged while switching retrieval input to focused chunks.
- [x] 2.3 Preserve query-only fallback when no attachment or no usable focus chunks are available.

## 3. Reasoning Prompt Integration

- [x] 3.1 Update grounded DeepSeek payload construction to use focused attachment summary/chunks instead of naive front excerpt.
- [x] 3.2 Keep response metadata (`attachment_used`, `attachment_file_name`) behavior unchanged.

## 4. Validation

- [x] 4.1 Verify attachment-driven retrieval no longer depends on the first file segment only.
- [x] 4.2 Verify no persistent ingestion/indexing path is triggered for uploaded chat attachments.
- [x] 4.3 Run regression checks for normal chat streaming and contract-review isolation.
