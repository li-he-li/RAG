## Context

Normal-mode uploads already exist in the frontend session state and there is a backend session temp-file store with `chat_attachment` kind.  
However, the normal chat retrieval request currently sends only query parameters, so similar-case retrieval cannot use uploaded case content.

This change must bridge that gap without affecting contract-review flow. The system should remain backward-compatible for clients that do not send new fields.

## Goals / Non-Goals

**Goals:**
- Make normal chat retrieval attachment-aware by default.
- Reuse existing session temp-file storage and lifecycle.
- Keep retrieval resilient: no attachment or unreadable attachment MUST fall back to query-only behavior.
- Improve user transparency by explicitly indicating when attachment-driven retrieval is used.

**Non-Goals:**
- No contract-review behavior changes.
- No manual attachment picker UI in this iteration.
- No changes to persistent document ingestion/indexing paths.

## Decisions

### 1) Trigger mode: auto-prioritize latest chat attachment
- Decision: when a normal-mode message is sent, backend attempts to use the latest available `chat_attachment` in the session.
- Rationale: matches user expectation with minimum interaction overhead.
- Alternative considered: explicit user command ("search by attachment") only. Rejected for higher friction and missed intent.

### 2) Multi-file policy: latest file only
- Decision: if multiple chat attachments exist, only the most recently uploaded and not deleted file is used.
- Rationale: deterministic behavior and lower noise compared with concatenating all files.
- Alternative considered: merge all files. Rejected due to prompt/query dilution and unpredictable retrieval quality.

### 3) Query construction: attachment content + user query
- Decision: retrieval query text is constructed from the chosen attachment content plus user message; enforce a bounded text size before embedding.
- Rationale: attachment captures case facts, while user query captures intent focus (e.g., "look for labor dispute cases").
- Alternative considered: attachment-only query. Rejected because user intent modifiers would be lost.

### 4) API compatibility strategy
- Decision: extend `ChatRequest` with optional `session_id` and `use_chat_attachment`; default remains current behavior if absent.
- Rationale: safe rollout with no breaking change for existing clients.
- Alternative considered: hard-require session context. Rejected because it would break current callers.

### 5) User-facing traceability signal
- Decision: include `attachment_used` and `attachment_file_name` metadata in chat-stream done payload and show a top notice in main chat response.
- Rationale: avoids ambiguity about retrieval basis and reduces support/debug confusion.
- Alternative considered: no UI signal. Rejected because behavior would appear opaque.

## Risks / Trade-offs

- [Large attachment content can hurt embedding latency/quality] -> Mitigation: apply strict content-length cap before query encoding.
- [Attachment parse quality varies by source format] -> Mitigation: if extracted content is empty/invalid, fall back to query-only retrieval.
- [Automatic mode may surprise some users] -> Mitigation: explicit "attachment used" response notice in UI.
- [Session/file mismatch due to stale frontend state] -> Mitigation: backend treats missing file as soft failure and continues query-only.

## Migration Plan

1. Add optional request fields and backend attachment-aware retrieval path behind soft checks.
2. Update frontend normal submit payload to pass `session_id` and `use_chat_attachment=true`.
3. Add response metadata + frontend notice rendering.
4. Run regression tests for normal chat, contract review, and no-attachment fallback.

Rollback: disable frontend `use_chat_attachment` flag and/or ignore new fields server-side; old query-only behavior remains intact.

## Open Questions

- None for v1; decisions are locked for implementation.
