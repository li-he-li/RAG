# Frontend Integration Guide

This document defines field semantics and rendering guidance for integrating
the legal similarity APIs in the web frontend.

## 1. API Base

- Base URL: `http://localhost:8000/api`
- Content type: `application/json`

## 2. Endpoints

### 2.1 Grounded Chat (Recommended for QA)

- Method: `POST`
- Path: `/chat`
- Request schema:
```json
{
  "query": "合同违约赔偿标准是什么？",
  "top_k_documents": 3,
  "top_k_paragraphs": 8,
  "dispute_focus": "合同违约"
}
```

- Response schema (200):
```json
{
  "query": "合同违约赔偿标准是什么？",
  "answer": "……基于证据的回答……",
  "citations": [
    {
      "doc_id": "uuid",
      "file_name": "case_a.txt",
      "line_start": 120,
      "line_end": 138,
      "version_id": "a1b2c3d4",
      "snippet": "……证据片段……",
      "similarity_score": 0.83
    }
  ],
  "grounded": true,
  "used_documents": 2,
  "timestamp": "2026-03-28T12:34:56.000000"
}
```

### 2.2 Similarity Search (Document + Evidence)

- Method: `POST`
- Path: `/search`
- Request schema:
```json
{
  "query": "劳动争议解除劳动合同",
  "top_k_documents": 5,
  "top_k_paragraphs": 10,
  "dispute_focus": "劳动争议"
}
```

- Response schema (200): `SearchResponse`
  - Top-level:
    - `query`: original query
    - `total_documents`: number of matched documents
    - `total_paragraphs`: number of evidence paragraphs
    - `results`: ordered document list
  - Each `results[i]` (`DocumentResult`):
    - `doc_id`, `file_name`, `source_path`, `version_id`, `total_lines`
    - `similarity_score`: document-level similarity
    - `paragraphs`: evidence list
  - Each `paragraphs[j]` (`ParagraphEvidence`):
    - `para_id`, `doc_id`, `line_start`, `line_end`
    - `dispute_tags`: dispute labels
    - `snippet`: evidence text
    - `match_explanation`: explanation text
    - `similarity_score`: paragraph-level score
    - `citation`: includes `file_name`, `line_start`, `line_end`, `version_id`

## 3. Error Model (422 / 503)

Error schema:
```json
{
  "error": "citation_unresolved",
  "detail": "Unable to resolve citation reference for para_id=...",
  "citation_missing": false
}
```

### 3.1 422 Validation Errors

Possible `error` values:

- `citation_incomplete`: missing required citation fields
- `source_metadata_missing`: missing `file_name/source_path/version_id`
- `citation_unresolved`: citation line range cannot be resolved

Frontend handling:

- Render a blocking error banner.
- Show `detail` text directly.
- Suggest user to re-upload document or refresh index when unresolved.

### 3.2 503 Service Not Ready

Returned when bootstrap is not complete.

Frontend handling:

- Disable submit button temporarily.
- Display `detail` and a retry action.
- Optionally trigger `/health` polling.

## 4. Rendering Guidance

### 4.1 Chat UI (`/chat`)

- Main answer area: render `answer`.
- Citation area:
  - Show `[index] file_name line_start-line_end (version_id)`.
  - Show `snippet` in a collapsible card.
  - Optionally show `similarity_score` as percent.

### 4.2 Search UI (`/search`)

- Group by document card, then nested paragraph evidence cards.
- Keep document-level and paragraph-level scores visually distinct.
- Always display citation line range beside each evidence block.

## 5. Minimal Frontend Parse Contract

- Success condition: `response.ok === true`.
- Error condition:
  - If `!response.ok`, parse JSON and read `error`, `detail`.
  - Do not rely on nested `detail.detail`; use top-level `detail`.

