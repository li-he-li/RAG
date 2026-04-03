# Staged Rollout and Fallback Plan (Task 6.4)

This service now supports staged retrieval rollout controlled by environment variables.

## Controls

- `RETRIEVAL_ROLLOUT_STAGE`
  - `document_only`: only document-level retrieval (no paragraph evidence)
  - `dual_no_explain`: document + paragraph retrieval, skip LLM explanations
  - `dual_full` (default): full dual-layer retrieval with explanations
- `RETRIEVAL_ENABLE_FALLBACK`
  - `true` (default): when dual-layer path fails, auto-fallback to `document_only`
  - `false`: disable fallback and surface the original error

## Recommended Rollout Sequence

1. Stage 0: `document_only`
2. Stage 1: `dual_no_explain`
3. Stage 2: `dual_full`

Promote stage only if error rate and latency stay within acceptance thresholds.

## Fallback Behavior

- Trigger: any exception in dual-layer retrieval/ranking/explanation pipeline.
- Action: run document-only retrieval path for the same request.
- Visibility: backend log entry includes fallback marker:
  - `"Dual retrieval path failed; falling back to document-only mode."`
  - `"Search executed with rollout stage: ... (fallback=...)"`.

## Rollback Command Example

Set environment before backend start:

```powershell
$env:RETRIEVAL_ROLLOUT_STAGE='document_only'
$env:RETRIEVAL_ENABLE_FALLBACK='true'
```

