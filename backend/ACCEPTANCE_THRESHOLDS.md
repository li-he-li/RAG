# Acceptance Thresholds

This document defines production acceptance thresholds for legal similarity
retrieval and grounded dialogue.

## 1. Scope

- Retrieval APIs: `/api/search`, `/api/chat`
- Data domains: document-level similarity, dispute-focused paragraph evidence,
  citation traceability usability
- Environment baseline: single backend instance, standard local deployment

## 2. Quality Thresholds

### 2.1 Document-Level Hit Rate (Top-K)

- Metric: `TopKDocHitRate`
- Definition: proportion of queries where at least one gold relevant document
  appears in top K document results.
- Acceptance:
  - `Top3DocHitRate >= 0.78`
  - `Top5DocHitRate >= 0.88`

### 2.2 Dispute-Focus Precision

- Metric: `DisputeFocusPrecision@5`
- Definition: among top 5 returned paragraph evidence items, percentage whose
  dispute focus matches the query intent label.
- Acceptance:
  - `DisputeFocusPrecision@5 >= 0.72`

### 2.3 Citation Usability

- Metric: `CitationUsabilityRate`
- Definition: proportion of evidence items where frontend can directly locate
  the referenced snippet by `(file_name, line_start, line_end, version_id)`.
- Acceptance:
  - `CitationUsabilityRate >= 0.995`
  - `citation_incomplete` error rate `<= 0.1%` of retrieval responses
  - `citation_unresolved` error rate `<= 0.5%` of retrieval responses

## 3. Reliability Thresholds

### 3.1 API Success Rate

- Metric: `SuccessRate`
- Definition: percentage of non-5xx responses under normal load.
- Acceptance:
  - `/api/search` success rate `>= 99.0%`
  - `/api/chat` success rate `>= 98.0%`

### 3.2 Bootstrap Readiness

- Metric: `BootstrapReadyBeforeServe`
- Definition: retrieval endpoints must reject with 503 when bootstrap is not ready.
- Acceptance:
  - 100% of calls to `/api/search` and `/api/chat` return 503 before ready

## 4. Performance Budget (Initial Target)

These are initial launch budgets and may be tightened after profiling.

- `/api/search`:
  - `P50 <= 1.2s`
  - `P95 <= 2.8s`
- `/api/chat` (includes DeepSeek round-trip):
  - `P50 <= 4.0s`
  - `P95 <= 8.0s`

## 5. Evaluation Gate

A release candidate passes acceptance only if all conditions below are true:

- Quality thresholds in section 2 are met.
- Reliability thresholds in section 3 are met.
- No Sev-1 citation traceability defect is open.

