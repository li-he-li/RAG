## 1. Data Model and Contract Baseline

- [x] 1.1 Define retrieval response schema with document-level ranking and nested paragraph-level evidence fields
- [x] 1.2 Add document-level metadata fields (`doc_id`, `file_name`, `source_path`, `version_id`, `total_lines`)
- [x] 1.3 Add paragraph-level metadata fields (`para_id`, `doc_id`, `line_start`, `line_end`, `dispute_tags`)
- [x] 1.4 Define and document citation requirements (`file_name`, `line_start`, `line_end`, `version_id`) as mandatory response fields
- [x] 1.5 Define bootstrap configuration for automatic provisioning of PostgreSQL and Qdrant
- [x] 1.6 Define bootstrap configuration for automatic download and setup of `BAAI/bge-m3` and `bge-reranker-v2-m3`
- [x] 1.7 Define initialization preflight contract to block retrieval service start until automatic bootstrap is complete

## 2. Parsing, Segmentation, and Indexing

- [x] 2.1 Implement normalized text extraction pipeline to produce stable line mapping per document version
- [x] 2.2 Implement paragraph segmentation with dispute-focus tagging support
- [x] 2.3 Build document-level embedding index for whole-case similarity retrieval
- [x] 2.4 Build paragraph-level embedding index for dispute-focused evidence retrieval
- [x] 2.5 Implement index refresh flow that preserves version-aware traceability metadata

## 3. Retrieval and Ranking Pipeline

- [x] 3.1 Implement query understanding stage for case-level and dispute-focus intent
- [x] 3.2 Implement dual retrieval flow (document recall followed by paragraph recall in candidate documents)
- [x] 3.3 Implement ranking and aggregation logic to return coherent document-plus-evidence results
- [x] 3.4 Implement match explanation generation for each paragraph evidence hit

## 4. Traceability and Evidence Verification

- [x] 4.1 Enforce server-side validation that paragraph hits always include required citation metadata
- [x] 4.2 Add evidence snippet extraction logic aligned with returned line ranges
- [x] 4.3 Add version consistency checks to detect and flag stale line references

## 5. API Integration for Unified Web Frontend

- [x] 5.1 Expose similarity search API endpoint using the stable dual-layer response contract
- [x] 5.2 Add API-level error model for missing source metadata or unresolved citation references
- [x] 5.3 Produce integration documentation for frontend consumption (field semantics and rendering guidance)

## 6. Evaluation, Performance, and Rollout

- [x] 6.1 Build a labeled evaluation set for dispute-focus and case-similarity retrieval quality checks
- [x] 6.2 Define acceptance thresholds (Top-K hit rate, dispute-focus precision, citation usability)
- [x] 6.3 Run performance profiling for end-to-end retrieval latency and optimize bottlenecks
- [x] 6.4 Execute staged rollout and fallback plan (degrade to document-level retrieval when needed)
- [x] 6.5 Validate first-run bootstrap flow in clean environments (no preinstalled DB/model dependencies)

## 7. DeepSeek Grounded Dialogue Integration

- [x] 7.1 Add grounded chat API endpoint (`/api/chat`) for database-backed DeepSeek responses
- [x] 7.2 Ensure chat responses include evidence citations (`file_name`, `line_start`, `line_end`, `version_id`) from indexed data
- [x] 7.3 Switch frontend composer flow to use grounded chat endpoint and render answer with citations
