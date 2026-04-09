"""
Retrieval service: dual-layer legal similarity search pipeline.

Flow:
  1. Query understanding (case-level + dispute-focus intent)
  2. Document recall via Qdrant document-level collection
  3. Paragraph recall within candidate documents
  4. Reranking with bge-reranker-v2-m3
  5. Ranking and aggregation into coherent results
  6. LLM-driven match explanation generation via DeepSeek V3
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    RETRIEVAL_ENABLE_FALLBACK,
    RETRIEVAL_ROLLOUT_STAGE,
)
from app.models.db_tables import DocumentTable
from app.models.schemas import (
    CitationMetadata,
    DocumentResult,
    ParagraphEvidence,
    SearchRequest,
    SearchResponse,
)
from app.services.embedding import encode_query
from app.services.reranker import rerank
from app.services.vector_store import (
    get_qdrant_client,
    search_documents,
    search_paragraphs,
)

logger = logging.getLogger(__name__)

DEFAULT_EXPLANATION_CONCURRENCY = max(
    1, int(os.getenv("LLM_EXPLANATION_CONCURRENCY", "4"))
)
DEFAULT_EXPLANATION_LIMIT = max(
    1, int(os.getenv("LLM_EXPLANATION_MAX_PARAGRAPHS", "12"))
)
DEFAULT_EXPLANATION_TIMEOUT_SEC = max(
    5.0, float(os.getenv("LLM_EXPLANATION_TIMEOUT_SEC", "20"))
)


def _default_match_explanation(query: str, similarity_score: float) -> str:
    return (
        f"This paragraph is semantically relevant to query '{query}'. "
        f"(similarity: {similarity_score:.2f})"
    )


# ---------------------------------------------------------------------------
# 1. Query understanding
# ---------------------------------------------------------------------------

def understand_query(query: str, dispute_focus: Optional[str] = None) -> dict:
    """Analyze the query to extract retrieval parameters.

    Returns a dict with:
      - expanded_query: the original query (can be enhanced later)
      - dispute_tags: list of dispute-focus tags to filter on
    """
    return {
        "expanded_query": query,
        "dispute_tags": [dispute_focus] if dispute_focus else [],
    }


# ---------------------------------------------------------------------------
# 2. Dual retrieval: document recall -> paragraph recall
# ---------------------------------------------------------------------------

def dual_retrieve(
    query_vector: list[float],
    top_k_documents: int = 5,
    top_k_paragraphs: int = 10,
    doc_ids_filter: Optional[list[str]] = None,
    dispute_tags: Optional[list[str]] = None,
) -> tuple[list, list]:
    """Execute dual-layer retrieval.

    Returns:
        (doc_hits, para_hits) — raw Qdrant scored points.
    """
    client = get_qdrant_client()

    # Layer 1: Document-level recall
    doc_hits = search_documents(
        query_vector=query_vector,
        top_k=top_k_documents,
        client=client,
    )

    # Layer 2: Paragraph-level recall within candidate documents
    candidate_doc_ids = [hit.id for hit in doc_hits]
    if doc_ids_filter:
        candidate_doc_ids = [
            d for d in candidate_doc_ids if d in doc_ids_filter
        ] or doc_ids_filter

    if not candidate_doc_ids:
        return doc_hits, []

    paragraph_limit = max(1, top_k_paragraphs * len(candidate_doc_ids))

    para_hits = search_paragraphs(
        query_vector=query_vector,
        doc_ids=candidate_doc_ids,
        top_k=paragraph_limit,
        dispute_tags=dispute_tags if dispute_tags else None,
        client=client,
    )

    return doc_hits, para_hits


def retrieve_documents_only(
    query_vector: list[float],
    top_k_documents: int = 5,
) -> list:
    """Document-only retrieval mode for rollout fallback."""
    client = get_qdrant_client()
    return search_documents(
        query_vector=query_vector,
        top_k=top_k_documents,
        client=client,
    )


# ---------------------------------------------------------------------------
# 3. Ranking and aggregation
# ---------------------------------------------------------------------------

def rank_and_aggregate(
    query: str,
    doc_hits: list,
    para_hits: list,
    db: Session,
    top_k_paragraphs: int = 10,
) -> list[DocumentResult]:
    """Combine and rerank paragraph hits with a single global reranker call."""
    # Build doc_id -> score mapping from document hits
    doc_score_map: dict[str, float] = {}
    for hit in doc_hits:
        doc_score_map[str(hit.id)] = float(hit.score)

    # Prefetch document metadata in one SQL query.
    doc_ids = [str(hit.id) for hit in doc_hits]
    doc_records = (
        db.query(DocumentTable)
        .filter(DocumentTable.doc_id.in_(doc_ids))
        .all()
        if doc_ids
        else []
    )
    doc_record_map = {record.doc_id: record for record in doc_records}

    # Flatten all paragraph candidates once and rerank globally to avoid repeated model overhead.
    candidate_items: list[tuple[str, object, str]] = []
    for p in para_hits:
        payload = p.payload or {}
        doc_id = str(payload.get("doc_id", ""))
        if not doc_id:
            continue
        text = payload.get("content", "")
        if not text:
            from app.services.traceability import extract_evidence_snippet

            text = extract_evidence_snippet(
                db,
                doc_id,
                int(payload.get("line_start", 1) or 1),
                int(payload.get("line_end", 1) or 1),
            )
        candidate_items.append((doc_id, p, str(text or "")))

    rerank_score_by_index: dict[int, float] = {}
    if candidate_items:
        candidate_texts = [item[2] for item in candidate_items]
        try:
            reranked = rerank(query, candidate_texts, top_k=None)
            rerank_score_by_index = {idx: float(score) for idx, score in reranked}
        except Exception as exc:
            logger.warning("Reranker failed, falling back to vector scores: %s", exc)
            rerank_score_by_index = {}

    scored_by_doc: dict[str, list[tuple[float, object, str]]] = {}
    for idx, (doc_id, p, text) in enumerate(candidate_items):
        score = rerank_score_by_index.get(idx, float(getattr(p, "score", 0.0)))
        scored_by_doc.setdefault(doc_id, []).append((score, p, text))

    for doc_id in scored_by_doc:
        scored_by_doc[doc_id].sort(key=lambda x: x[0], reverse=True)
        scored_by_doc[doc_id] = scored_by_doc[doc_id][:top_k_paragraphs]

    results: list[DocumentResult] = []
    for doc_hit in doc_hits:
        doc_id = str(doc_hit.id)
        doc_payload = doc_hit.payload or {}

        doc_record = doc_record_map.get(doc_id)
        file_name = doc_payload.get("file_name", "")
        source_path = doc_payload.get("source_path", "")
        version_id = doc_payload.get("version_id", "")
        total_lines = int(doc_payload.get("total_lines", 0) or 0)

        if doc_record:
            file_name = doc_record.file_name
            source_path = doc_record.source_path
            version_id = doc_record.version_id
            total_lines = doc_record.total_lines

        paragraph_evidence: list[ParagraphEvidence] = []
        for score, p, snippet in scored_by_doc.get(doc_id, []):
            payload = p.payload or {}
            line_start = int(payload.get("line_start", 0) or 0)
            line_end = int(payload.get("line_end", 0) or 0)
            paragraph_evidence.append(
                ParagraphEvidence(
                    para_id=str(payload.get("para_id", str(p.id))),
                    doc_id=doc_id,
                    line_start=line_start,
                    line_end=line_end,
                    dispute_tags=payload.get("dispute_tags", []),
                    snippet=snippet[:500] if snippet else "",
                    similarity_score=float(score),
                    match_explanation="",
                    citation=CitationMetadata(
                        file_name=file_name,
                        line_start=line_start,
                        line_end=line_end,
                        version_id=version_id,
                    ),
                )
            )

        results.append(
            DocumentResult(
                doc_id=doc_id,
                file_name=file_name,
                source_path=source_path,
                version_id=version_id,
                total_lines=total_lines,
                similarity_score=doc_score_map.get(doc_id, float(doc_hit.score)),
                paragraphs=paragraph_evidence,
            )
        )

    return results


# ---------------------------------------------------------------------------
# 4. LLM-driven match explanation via DeepSeek V3
# ---------------------------------------------------------------------------

async def generate_explanations(
    query: str,
    results: list[DocumentResult],
) -> list[DocumentResult]:
    """Generate match explanations for each paragraph using DeepSeek V3 API.

    Uses concurrent requests (up to 4) instead of sequential calls.
    """
    import asyncio
    import httpx

    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not set, skipping LLM explanation generation")
        for doc in results:
            for para in doc.paragraphs:
                if not para.match_explanation:
                    para.match_explanation = f"该段落与查询「{query}」在语义上高度相关（相似度: {para.similarity_score:.2f}）"
        return results

    system_prompt = (
        "你是一个法律文书检索辅助分析系统。用户正在进行法律文书的相似性检索，"
        "你需要根据查询和匹配到的段落内容，简要说明该段落与查询的相关性。"
        "要求：用中文回答，1-3句话，直接说明相关性，不要多余寒暄。"
    )

    fallback_explanation = "该段落与查询「{query}」在语义上高度相关（相似度: {score:.2f}）"

    # Collect all tasks
    async def _explain_one(client: httpx.AsyncClient, para: ParagraphEvidence) -> None:
        try:
            user_message = (
                f"查询：{query}\n\n"
                f"匹配段落（来源: {para.citation.file_name}, "
                f"第{para.citation.line_start}-{para.citation.line_end}行）：\n"
                f"{para.snippet}\n\n"
                f"请简要说明该段落与查询的相关性。"
            )
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                para.match_explanation = data["choices"][0]["message"]["content"].strip()
            else:
                logger.warning("DeepSeek explanation API returned %s", resp.status_code)
                para.match_explanation = fallback_explanation.format(query=query, score=para.similarity_score)
        except Exception as e:
            logger.warning("DeepSeek API call failed: %s", e)
            para.match_explanation = fallback_explanation.format(query=query, score=para.similarity_score)

    # Gather all paragraphs
    tasks: list = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for doc in results:
            for para in doc.paragraphs:
                tasks.append(_explain_one(client, para))
        # Run up to 4 concurrently
        semaphore = asyncio.Semaphore(4)

        async def _bounded(task_coro):
            async with semaphore:
                await task_coro

        await asyncio.gather(*[_bounded(t) for t in tasks])

    return results


# ---------------------------------------------------------------------------
# 5. Main search orchestrator
# ---------------------------------------------------------------------------

async def execute_search(
    request: SearchRequest,
    db: Session,
) -> SearchResponse:
    """Execute search with staged rollout and document-only fallback support."""
    parsed_query = understand_query(request.query, request.dispute_focus)
    query_vector = encode_query(parsed_query["expanded_query"])

    stage = RETRIEVAL_ROLLOUT_STAGE
    used_fallback = False

    def _document_only_results() -> list[DocumentResult]:
        doc_hits = retrieve_documents_only(
            query_vector=query_vector,
            top_k_documents=request.top_k_documents,
        )
        return rank_and_aggregate(
            query=request.query,
            doc_hits=doc_hits,
            para_hits=[],
            db=db,
            top_k_paragraphs=request.top_k_paragraphs,
        )

    try:
        if stage == "document_only":
            results = _document_only_results()
        else:
            doc_hits, para_hits = dual_retrieve(
                query_vector=query_vector,
                top_k_documents=request.top_k_documents,
                top_k_paragraphs=request.top_k_paragraphs,
                dispute_tags=parsed_query["dispute_tags"],
            )
            results = rank_and_aggregate(
                query=request.query,
                doc_hits=doc_hits,
                para_hits=para_hits,
                db=db,
                top_k_paragraphs=request.top_k_paragraphs,
            )
            if stage == "dual_full":
                results = await generate_explanations(request.query, results)
    except Exception:
        if not RETRIEVAL_ENABLE_FALLBACK:
            raise
        logger.exception(
            "Dual retrieval path failed; falling back to document-only mode."
        )
        used_fallback = True
        results = _document_only_results()

    total_paragraphs = sum(len(doc.paragraphs) for doc in results)
    effective_stage = "document_only" if used_fallback else stage
    logger.info(
        "Search executed with rollout stage: %s (fallback=%s)",
        effective_stage,
        used_fallback,
    )
    return SearchResponse(
        query=request.query,
        total_documents=len(results),
        total_paragraphs=total_paragraphs,
        results=results,
    )
