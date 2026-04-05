## Why

The current attachment-driven similar-case retrieval path uses the latest uploaded case file by taking only the first fixed-length text slice.
This is not reliable for long case materials because key facts, dispute focus, or court reasoning often appear later in the file.

To make uploaded-file similarity search trustworthy, the system must select the most relevant attachment sections based on the user's query before searching the case database.

## What Changes

- Replace fixed front-truncation of chat attachment text with query-aware attachment focus selection.
- Segment the uploaded attachment into normalized chunks in temporary runtime only.
- Rank attachment chunks against the user's query and use the highest-signal chunks to build retrieval input.
- Pass attachment focus summary and selected chunks into DeepSeek reasoning prompt instead of a naive front excerpt.
- Keep all attachment processing session-scoped and out of the persistent case/document index.

## Capabilities

### New Capabilities
- `chat-attachment-similarity-focus`: Select the most relevant sections from an uploaded chat attachment before similar-case retrieval and explanation.

### Modified Capabilities
- `chat-attachment-driven-retrieval`: Improve attachment retrieval quality by replacing head-only truncation with query-aware focused chunks.

## Impact

- Affected backend services: `backend/app/services/chat.py` and new attachment-focus helper logic.
- Affected retrieval behavior: similar-case search input composition for normal chat mode.
- No persistent database/vector-store writes for uploaded case files.
- No contract-review flow changes.
