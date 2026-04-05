## Context

Normal chat already supports session-scoped `chat_attachment` files and can use them as retrieval input for similar-case search.
However, the current implementation simply concatenates the user's query with the first 5000 characters of the latest attachment.
That makes retrieval quality fragile for long or front-heavy files.

This change must improve attachment relevance selection without polluting the persistent database or vector index.

## Goals / Non-Goals

**Goals**
- Select attachment text based on the current user query rather than file head position.
- Keep all attachment chunking and scoring in temporary runtime/session scope only.
- Reuse the existing retrieval pipeline after attachment focus selection.
- Improve DeepSeek explanation quality by supplying focused case material rather than naive truncation.

**Non-Goals**
- No persistent ingestion of user-uploaded files into PostgreSQL/Qdrant.
- No frontend workflow changes for sending requests.
- No contract-review pipeline changes.

## Decisions

### 1) Focus selection happens before database retrieval
- Decision: when `use_chat_attachment=true`, backend first resolves the latest session `chat_attachment`, segments it, scores segments against the user query, and only then constructs retrieval input.
- Rationale: this directly fixes the weak point of the current implementation.

### 2) Segment by normalized paragraphs and short sliding windows
- Decision: use existing paragraph parsing to derive candidate chunks, then build small adjacent windows to preserve context across short paragraphs.
- Rationale: better than fixed character slicing and avoids introducing a second parsing system.

### 3) Rank chunks with embedding similarity plus light lexical bonus
- Decision: rank attachment chunks with query-vs-chunk semantic similarity and small keyword overlap bonus.
- Rationale: keeps implementation aligned with current retrieval stack and improves stability for exact-dispute terms.

### 4) Retrieval input uses focused chunks, not full attachment head
- Decision: the final retrieval query text is composed from selected attachment chunks plus the user query.
- Rationale: preserves user intent while reducing noise from irrelevant parts of the attachment.

### 5) Prompt input distinguishes overview from focus chunks
- Decision: DeepSeek receives:
  - attachment file name
  - attachment focus summary
  - top selected attachment chunks
  - retrieved database evidence
- Rationale: makes case-to-case reasoning more explicit and less dependent on arbitrary truncation.

### 6) Temporary-only processing
- Decision: chunking, scoring, and any embeddings derived from uploaded attachments stay in-process for the current request and are never written to persistent case storage.
- Rationale: avoids database pollution and preserves clear separation between product case corpus and user session materials.

## Risks / Trade-offs

- [Large attachments may increase per-request latency] -> Mitigation: cap candidate chunk count and focused output length.
- [Embedding many chunks per request can be expensive] -> Mitigation: reuse paragraph parser, keep chunk windows bounded, score only the latest attachment.
- [Very noisy OCR/PDF extraction may still degrade results] -> Mitigation: fallback to query-only retrieval if focused chunk selection yields no usable text.
- [Small-file cases might not need chunk ranking] -> Mitigation: helper can return full text when file is already short.

## Migration Plan

1. Add session-scoped attachment focus helper service.
2. Replace front-truncation logic in grounded chat retrieval with focused chunk selection.
3. Update DeepSeek prompt construction to use focus summary/chunks.
4. Verify fallback behavior when no usable chunks are found.

Rollback: restore previous fixed truncation path in `chat.py`; session temp file APIs remain unchanged.

## Open Questions

- None for this iteration. Frontend request format remains unchanged.
