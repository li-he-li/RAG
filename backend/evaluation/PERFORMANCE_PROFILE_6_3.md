# 6.3 Performance Profiling and Bottleneck Optimization

Date: 2026-03-29

## Scope

- Target pipeline: retrieval end-to-end (`understand -> encode -> retrieve -> rank -> explain -> traceability`)
- Script: `backend/evaluation/profile_retrieval_pipeline.py`
- Runs per profile: 5
- Query: `合同违约导致赔偿责任如何认定`
- Request shape: `top_k_documents=3`, `top_k_paragraphs=6`

## Raw Results

- Baseline JSON: `backend/evaluation/perf_baseline_6_3.json`
- Optimized JSON: `backend/evaluation/perf_optimized_6_3.json`

### Baseline (before optimization)

- `total_p50_ms`: `3363.99`
- `total_p95_ms`: `16578.52` (cold start on first run)
- Stage bottleneck (`steady runs`): `rank_ms` around `3.0s`

### Optimized (after optimization)

- `total_p50_ms`: `3072.83`
- `total_p95_ms`: `14805.47` (cold start on first run)
- Stage bottleneck (`steady runs`): `rank_ms` around `2.73s ~ 2.87s`

## Optimization Applied

### 1) Rerank stage optimization (primary bottleneck)

File: `backend/app/services/retrieval.py`

- Before:
  - reranker invoked once per document candidate group
  - repeated model compute overhead in loop
- After:
  - flatten all paragraph candidates
  - run a single global rerank call
  - split and truncate top-k per document after scoring

Effect:
- `rank_ms` steady-state reduced by about `8%+`
- `total_p50_ms` improved from `3363.99` to `3072.83` (about `8.7%`)

### 2) Runtime model-loading robustness for profiling environment

Files:
- `backend/app/services/embedding.py`
- `backend/app/services/reranker.py`

Changes:
- Prefer local snapshot path under `backend/data/models_cache`
- Use `local_files_only=True` when local snapshots exist

Reason:
- Current environment blocks outbound HuggingFace access; this enables repeatable local profiling.

## Notes

- DeepSeek API call attempts failed in this environment (`All connection attempts failed`), so `explain_ms` reflects fast-fallback behavior rather than real external API latency.
- Profiling is still valid for retrieval core bottleneck isolation and optimization verification.
