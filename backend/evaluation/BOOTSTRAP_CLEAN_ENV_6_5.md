# 6.5 Clean Environment Bootstrap Validation

Date: 2026-03-29

## Validation Goal

Validate first-run bootstrap behavior in a clean runtime state (no running PostgreSQL/Qdrant containers before startup).

## Validation Method

Script: `backend/evaluation/validate_bootstrap_clean_env.py`

Steps executed by script:

1. Detect existing managed containers:
   - `legal-search-postgres`
   - `legal-search-qdrant`
2. Remove those containers to simulate clean first start.
3. Run `run_bootstrap()`.
4. Verify:
   - PostgreSQL container recreated and running
   - Qdrant container recreated and running
   - embedding/reranker model readiness checks pass

## Result

- Report JSON: `backend/evaluation/bootstrap_clean_env_report.json`
- Outcome: `all_ready = true`
- End-to-end bootstrap duration: `26.15s`

Key status:

- `postgresql_ready: true`
- `qdrant_ready: true`
- `embedding_model_ready: true`
- `reranker_model_ready: true`
- `all_ready: true`

## Notes

- Model readiness was validated from local snapshots under `backend/data/models_cache`.
- This confirms clean first-run bootstrap behavior for service dependencies and model availability checks in the current environment.
