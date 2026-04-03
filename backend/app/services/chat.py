"""
Grounded DeepSeek chat service.

Pipeline:
1. Retrieve evidence from indexed documents (Qdrant + PostgreSQL metadata).
2. Build evidence context for DeepSeek when citations exist.
3. If no citation is found, still call DeepSeek in non-grounded mode.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from app.core.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.models.schemas import ChatCitation, ChatRequest, ChatResponse
from app.services.embedding import encode_single
from app.services.retrieval import dual_retrieve, rank_and_aggregate, understand_query
from app.services.traceability import validate_and_enrich_results

logger = logging.getLogger(__name__)


def _collect_citations(
    request: ChatRequest,
    db: Session,
) -> list[ChatCitation]:
    """Retrieve and flatten citation evidence for a chat query."""
    try:
        parsed_query = understand_query(request.query, request.dispute_focus)
        query_vector = encode_single(parsed_query["expanded_query"])

        doc_hits, para_hits = dual_retrieve(
            query_vector=query_vector,
            top_k_documents=request.top_k_documents,
            top_k_paragraphs=request.top_k_paragraphs,
            dispute_tags=parsed_query["dispute_tags"],
        )

        doc_results = rank_and_aggregate(
            query=request.query,
            doc_hits=doc_hits,
            para_hits=para_hits,
            db=db,
            top_k_paragraphs=request.top_k_paragraphs,
        )
        doc_results = validate_and_enrich_results(db, doc_results)
    except Exception as exc:
        logger.exception("Citation retrieval failed, fallback to non-grounded chat: %s", exc)
        return []

    ranked: list[tuple[float, ChatCitation]] = []
    seen: set[tuple[str, int, int, str]] = set()

    for doc in doc_results:
        for para in doc.paragraphs:
            key = (
                para.doc_id,
                para.citation.line_start,
                para.citation.line_end,
                para.citation.version_id,
            )
            if key in seen:
                continue
            seen.add(key)
            ranked.append(
                (
                    float(para.similarity_score),
                    ChatCitation(
                        doc_id=para.doc_id,
                        file_name=para.citation.file_name,
                        line_start=para.citation.line_start,
                        line_end=para.citation.line_end,
                        version_id=para.citation.version_id,
                        snippet=(para.snippet or "").strip(),
                        similarity_score=float(para.similarity_score),
                    ),
                )
            )

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in ranked[: request.top_k_paragraphs]]


def _build_context(citations: list[ChatCitation]) -> str:
    """Build plain-text evidence context for DeepSeek."""
    chunks = []
    for idx, c in enumerate(citations, start=1):
        chunks.append(
            "\n".join(
                [
                    f"[{idx}]",
                    f"doc_id: {c.doc_id}",
                    f"file_name: {c.file_name}",
                    f"version_id: {c.version_id}",
                    f"line_range: {c.line_start}-{c.line_end}",
                    "snippet:",
                    c.snippet or "(empty)",
                ]
            )
        )
    return "\n\n".join(chunks)


def _fallback_answer(citations: list[ChatCitation]) -> str:
    """Deterministic fallback when DeepSeek is unavailable."""
    if not citations:
        return (
            "当前知识库没有命中证据，且 DeepSeek 服务暂不可用。"
            "请稍后重试，或先上传相关文档后再提问。"
        )

    lines = ["DeepSeek 暂不可用，以下是数据库证据摘要："]
    for c in citations[:3]:
        snippet = c.snippet.replace("\n", " ").strip()
        if len(snippet) > 140:
            snippet = snippet[:140] + "..."
        lines.append(
            f"- {c.file_name} 第{c.line_start}-{c.line_end}行（v{c.version_id}）：{snippet}"
        )
    return "\n".join(lines)


async def _ask_deepseek(query: str, citations: list[ChatCitation]) -> str:
    """Ask DeepSeek, grounded when evidence exists, general otherwise."""
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY is empty, using fallback answer")
        return _fallback_answer(citations)

    if citations:
        evidence_context = _build_context(citations)
        system_prompt = (
            "你是法律检索问答助手。你只能依据给定数据库证据回答，"
            "不要编造事实。关键结论后请标注证据编号，如 [1][2]。"
        )
        user_prompt = (
            f"用户问题：{query}\n\n"
            "可用证据如下：\n"
            f"{evidence_context}\n\n"
            "请给出简明答案并附证据编号。"
        )
        temperature = 0.1
    else:
        system_prompt = (
            "你是法律问答助手。当前知识库未命中证据，"
            "请按一般法律知识回答，并明确说明这不是数据库证据结论。"
        )
        user_prompt = (
            f"用户问题：{query}\n\n"
            "当前知识库无可引用证据，请先给出通用建议。"
        )
        temperature = 0.3

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
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
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": 700,
                },
            )
    except Exception as exc:
        logger.warning("DeepSeek chat request failed: %s", exc)
        return _fallback_answer(citations)

    if resp.status_code != 200:
        logger.warning("DeepSeek chat failed: status=%s body=%s", resp.status_code, resp.text[:300])
        return _fallback_answer(citations)

    try:
        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        if answer:
            return answer
    except Exception as exc:
        logger.warning("DeepSeek response parsing failed: %s", exc)

    return _fallback_answer(citations)


async def execute_grounded_chat(
    request: ChatRequest,
    db: Session,
) -> ChatResponse:
    """Execute grounded chat over indexed legal evidence."""
    citations = _collect_citations(request, db)
    answer = await _ask_deepseek(request.query, citations)

    return ChatResponse(
        query=request.query,
        answer=answer,
        citations=citations,
        grounded=bool(citations),
        used_documents=len({c.doc_id for c in citations}),
    )
