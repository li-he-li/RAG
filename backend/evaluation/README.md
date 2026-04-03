# Labeled Evaluation Set

This directory contains the labeled dataset used by task `6.1` for retrieval
quality checks (case similarity + dispute-focused evidence localization).

## Files

- `labeled_eval_set.jsonl`: seed labeled set (one JSON object per line)

## Record Schema

Each JSONL line follows:

```json
{
  "id": "eval-001",
  "query": "合同违约后如何计算损失赔偿",
  "dispute_focus_label": "contract_breach",
  "case_similarity_goal": "case_level_and_evidence_level",
  "gold_documents": [
    { "file_name": "contract_breach_case_001.txt", "relevance": 3 }
  ],
  "gold_evidence": [
    {
      "file_name": "contract_breach_case_001.txt",
      "line_start": 118,
      "line_end": 146,
      "dispute_tags": ["合同违约", "损害赔偿"]
    }
  ],
  "must_have_citation": true
}
```

## Labeling Rules

- `gold_documents`:
  - `relevance=3`: highly relevant same-type precedent
  - `relevance=2`: useful supporting precedent
  - `relevance=1`: weak but still related
- `gold_evidence`: paragraph-level supervision targets for dispute-focused
  retrieval and citation traceability checks.
- `must_have_citation=true`: returned evidence must include
  `file_name/line_start/line_end/version_id`.

## Coverage

Current seed set covers 10 dispute domains:

- contract breach
- labor dispute
- housing lease
- debt dispute
- intellectual property
- marriage/family
- inheritance
- criminal fraud
- administrative penalty
- procedural matters

## Notes

- This is a seed set for acceptance and regression checks.
- Additional records can be appended using the same schema.
