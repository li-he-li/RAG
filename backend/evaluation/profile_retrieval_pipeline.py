"""
Profile end-to-end retrieval latency with per-stage timing.

Runs the retrieval pipeline directly:
query -> encode -> dual retrieve -> rank -> explain -> traceability validate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from app.core.database import SessionLocal
from app.models.schemas import SearchRequest
from app.services.retrieval import (
    dual_retrieve,
    encode_single,
    generate_explanations,
    rank_and_aggregate,
    understand_query,
)
from app.services.traceability import validate_and_enrich_results


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return ordered[idx]


async def run_once(request: SearchRequest) -> dict[str, float | int]:
    db = SessionLocal()
    try:
        t0 = time.perf_counter()
        parsed = understand_query(request.query, request.dispute_focus)
        t1 = time.perf_counter()

        query_vector = encode_single(parsed["expanded_query"])
        t2 = time.perf_counter()

        doc_hits, para_hits = dual_retrieve(
            query_vector=query_vector,
            top_k_documents=request.top_k_documents,
            top_k_paragraphs=request.top_k_paragraphs,
            dispute_tags=parsed["dispute_tags"],
        )
        t3 = time.perf_counter()

        results = rank_and_aggregate(
            query=request.query,
            doc_hits=doc_hits,
            para_hits=para_hits,
            db=db,
            top_k_paragraphs=request.top_k_paragraphs,
        )
        t4 = time.perf_counter()

        results = await generate_explanations(request.query, results)
        t5 = time.perf_counter()

        _ = validate_and_enrich_results(db, results)
        t6 = time.perf_counter()

        return {
            "total_ms": (t6 - t0) * 1000.0,
            "understand_ms": (t1 - t0) * 1000.0,
            "encode_ms": (t2 - t1) * 1000.0,
            "retrieve_ms": (t3 - t2) * 1000.0,
            "rank_ms": (t4 - t3) * 1000.0,
            "explain_ms": (t5 - t4) * 1000.0,
            "traceability_ms": (t6 - t5) * 1000.0,
            "doc_hits": len(doc_hits),
            "para_hits": sum(len(doc.paragraphs) for doc in results),
        }
    finally:
        db.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--query", default="合同违约导致赔偿责任如何认定")
    parser.add_argument("--dispute-focus", default=None)
    parser.add_argument("--top-k-documents", type=int, default=3)
    parser.add_argument("--top-k-paragraphs", type=int, default=6)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    request = SearchRequest(
        query=args.query,
        dispute_focus=args.dispute_focus,
        top_k_documents=args.top_k_documents,
        top_k_paragraphs=args.top_k_paragraphs,
    )

    rows: list[dict[str, float | int]] = []
    for i in range(args.runs):
        row = await run_once(request)
        rows.append(row)
        print(
            f"run={i+1} total={row['total_ms']:.2f}ms "
            f"encode={row['encode_ms']:.2f} retrieve={row['retrieve_ms']:.2f} "
            f"rank={row['rank_ms']:.2f} explain={row['explain_ms']:.2f} "
            f"trace={row['traceability_ms']:.2f} docs={row['doc_hits']} paras={row['para_hits']}"
        )

    totals = [float(r["total_ms"]) for r in rows]
    explain = [float(r["explain_ms"]) for r in rows]
    summary = {
        "runs": len(rows),
        "total_p50_ms": statistics.median(totals),
        "total_p95_ms": p95(totals),
        "explain_p50_ms": statistics.median(explain),
        "explain_p95_ms": p95(explain),
        "rows": rows,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
