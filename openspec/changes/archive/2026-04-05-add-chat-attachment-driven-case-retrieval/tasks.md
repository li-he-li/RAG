## 1. Backend Request and Retrieval Wiring

- [x] 1.1 Extend `ChatRequest` with optional `session_id` and `use_chat_attachment` fields while preserving backward compatibility.
- [x] 1.2 Add helper logic in grounded chat/retrieval flow to resolve latest session `chat_attachment` from temp file store.
- [x] 1.3 Build attachment-aware retrieval query composition (`attachment content + user query`) with bounded content length.
- [x] 1.4 Implement safe fallback to query-only retrieval when attachment resolution or content usability fails.

## 2. Chat Response Metadata

- [x] 2.1 Add attachment-usage metadata fields (`attachment_used`, `attachment_file_name`) to chat stream/non-stream response payload assembly.
- [x] 2.2 Ensure metadata is populated only when attachment-driven retrieval is actually used.
- [x] 2.3 Keep legacy response behavior unchanged for requests without attachment context.

## 3. Frontend Normal-Mode Integration

- [x] 3.1 Update normal-mode submit request to include `session_id` and `use_chat_attachment=true`.
- [x] 3.2 Render an explicit notice in main chat messages when response metadata indicates attachment-driven retrieval.
- [x] 3.3 Keep contract-review mode request/response path unchanged and isolated from this feature.

## 4. Validation and Regression

- [x] 4.1 Verify normal-mode retrieval with one attachment uses attachment source and returns similarity/citations as expected.
- [x] 4.2 Verify multi-attachment behavior uses the latest available attachment by default.
- [x] 4.3 Verify deletion path removes attachment from future retrieval source selection.
- [x] 4.4 Verify no-attachment and attachment-error cases gracefully fall back to query-only retrieval.
- [x] 4.5 Run regression checks to confirm contract-review flow and existing chat streaming behavior remain intact.
