"""
Grounded DeepSeek chat service.

Pipeline:
1. Retrieve evidence from indexed documents (Qdrant + PostgreSQL metadata).
2. Build evidence context for DeepSeek when citations exist.
3. If no citation is found, still call DeepSeek in non-grounded mode.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.models.schemas import ChatCitation, ChatRequest, ChatResponse, SessionTempFileKind
from app.services.embedding import encode_single
from app.services.retrieval import dual_retrieve, rank_and_aggregate, understand_query
from app.services.session_files import session_temp_file_store
from app.services.traceability import validate_and_enrich_results

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_QUERY_CHARS = 5000
MAX_ATTACHMENT_PROMPT_CHARS = 3000


@dataclass(slots=True)
class ChatRetrievalInput:
    query_text: str
    attachment_used: bool = False
    attachment_file_name: str | None = None
    attachment_excerpt: str | None = None


def _normalize_session_id(session_id: str | None) -> str | None:
    if not isinstance(session_id, str):
        return None
    normalized = session_id.strip()
    return normalized or None


def _build_attachment_query_input(request: ChatRequest) -> ChatRetrievalInput:
    session_id = _normalize_session_id(request.session_id)
    if not request.use_chat_attachment or not session_id:
        return ChatRetrievalInput(query_text=request.query)

    records = session_temp_file_store.get_files(
        session_id=session_id,
        kind=SessionTempFileKind.CHAT_ATTACHMENT,
    )
    if not records:
        return ChatRetrievalInput(query_text=request.query)

    latest = records[-1]
    attachment_content = (latest.content or "").strip()
    if not attachment_content:
        return ChatRetrievalInput(query_text=request.query)

    clipped = attachment_content[:MAX_ATTACHMENT_QUERY_CHARS]
    query_text = f"{clipped}\n\n{request.query}"
    return ChatRetrievalInput(
        query_text=query_text,
        attachment_used=True,
        attachment_file_name=latest.file_name,
        attachment_excerpt=attachment_content[:MAX_ATTACHMENT_PROMPT_CHARS],
    )


def _collect_citations(
    request: ChatRequest,
    db: Session,
) -> tuple[list[ChatCitation], ChatRetrievalInput]:
    """Retrieve and flatten citation evidence for a chat query."""
    retrieval_input = _build_attachment_query_input(request)
    try:
        parsed_query = understand_query(retrieval_input.query_text, request.dispute_focus)
        query_vector = encode_single(parsed_query["expanded_query"])

        doc_hits, para_hits = dual_retrieve(
            query_vector=query_vector,
            top_k_documents=request.top_k_documents,
            top_k_paragraphs=request.top_k_paragraphs,
            dispute_tags=parsed_query["dispute_tags"],
        )

        doc_results = rank_and_aggregate(
            query=retrieval_input.query_text,
            doc_hits=doc_hits,
            para_hits=para_hits,
            db=db,
            top_k_paragraphs=request.top_k_paragraphs,
        )
        doc_results = validate_and_enrich_results(db, doc_results)
    except Exception as exc:
        logger.exception("Citation retrieval failed, fallback to non-grounded chat: %s", exc)
        return [], ChatRetrievalInput(query_text=request.query)

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
    return [item[1] for item in ranked[: request.top_k_paragraphs]], retrieval_input


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


def _build_deepseek_payload(
    query: str,
    citations: list[ChatCitation],
    retrieval_input: ChatRetrievalInput,
    *,
    stream: bool,
) -> dict:
    """Build a DeepSeek chat-completions payload."""
    if citations:
        evidence_context = _build_context(citations)
        if retrieval_input.attachment_used and retrieval_input.attachment_excerpt:
            system_prompt = (
                "你是法律类案检索对比助手。你需要同时参考用户上传的原案件材料和给定数据库证据回答。"
                "不要忽略原案件内容，也不要编造事实。"
                "请明确说明候选案例与原案件的相似点、差异点，以及你判断相似的原因。"
                "引用数据库证据时请标注证据编号，如 [1][2]。"
            )
            user_prompt = (
                f"用户问题：{query}\n\n"
                f"用户上传的原案件材料（文件：{retrieval_input.attachment_file_name or '未命名附件'}）：\n"
                f"{retrieval_input.attachment_excerpt}\n\n"
                "数据库检索到的候选证据如下：\n"
                f"{evidence_context}\n\n"
                "请基于原案件材料与候选证据进行回答，至少覆盖：\n"
                "1. 哪些案例与原案件更相似\n"
                "2. 相似主要体现在哪些事实或争议点\n"
                "3. 如果证据不足以支持强对比，要明确指出不足"
            )
        else:
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
        if retrieval_input.attachment_used and retrieval_input.attachment_excerpt:
            system_prompt = (
                "你是法律类案检索助手。当前知识库没有命中可引用案例证据。"
                "你可以参考用户上传的原案件材料说明当前无法完成强相似案例对比，"
                "但不要把没有证据支撑的内容说成数据库结论。"
            )
            user_prompt = (
                f"用户问题：{query}\n\n"
                f"用户上传的原案件材料（文件：{retrieval_input.attachment_file_name or '未命名附件'}）：\n"
                f"{retrieval_input.attachment_excerpt}\n\n"
                "当前知识库无可引用证据。请说明目前无法基于数据库给出可靠相似案例结论，"
                "并简要指出后续应补充什么信息。"
            )
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

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 700,
    }
    if stream:
        payload["stream"] = True
    return payload


def _iter_text_chunks(text: str, chunk_size: int = 24) -> list[str]:
    """Split fallback text into small chunks for frontend streaming."""
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


async def _ask_deepseek(query: str, citations: list[ChatCitation], retrieval_input: ChatRetrievalInput) -> str:
    """Ask DeepSeek, grounded when evidence exists, general otherwise."""
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY is empty, using fallback answer")
        return _fallback_answer(citations)

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=_build_deepseek_payload(query, citations, retrieval_input, stream=False),
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


async def _stream_deepseek(
    query: str,
    citations: list[ChatCitation],
    retrieval_input: ChatRetrievalInput,
) -> AsyncIterator[str]:
    """Stream DeepSeek answer tokens, falling back to chunked local text when needed."""
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY is empty, using fallback answer")
        for chunk in _iter_text_chunks(_fallback_answer(citations)):
            yield chunk
        return

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=_build_deepseek_payload(query, citations, retrieval_input, stream=True),
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="ignore")
                    logger.warning("DeepSeek stream failed: status=%s body=%s", resp.status_code, body[:300])
                    for chunk in _iter_text_chunks(_fallback_answer(citations)):
                        yield chunk
                    return

                streamed_any = False
                async for raw_line in resp.aiter_lines():
                    line = raw_line.strip()
                    if not line or not line.startswith("data:"):
                        continue

                    data = line[5:].strip()
                    if data == "[DONE]":
                        break

                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON DeepSeek stream payload: %s", data[:120])
                        continue

                    choices = payload.get("choices") or []
                    if not choices:
                        continue

                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if not content:
                        continue

                    streamed_any = True
                    yield str(content)

                if streamed_any:
                    return
    except Exception as exc:
        logger.warning("DeepSeek streaming request failed: %s", exc)

    for chunk in _iter_text_chunks(_fallback_answer(citations)):
        yield chunk


def _encode_stream_event(payload: dict) -> str:
    """Encode a streaming event as a single NDJSON line."""
    return json.dumps(payload, ensure_ascii=False) + "\n"


async def execute_grounded_chat(
    request: ChatRequest,
    db: Session,
) -> ChatResponse:
    """Execute grounded chat over indexed legal evidence."""
    citations, retrieval_input = _collect_citations(request, db)
    answer = await _ask_deepseek(request.query, citations, retrieval_input)

    return ChatResponse(
        query=request.query,
        answer=answer,
        citations=citations,
        grounded=bool(citations),
        used_documents=len({c.doc_id for c in citations}),
        attachment_used=retrieval_input.attachment_used,
        attachment_file_name=retrieval_input.attachment_file_name,
    )


async def stream_grounded_chat(
    request: ChatRequest,
    db: Session,
) -> AsyncIterator[str]:
    """Stream grounded chat as NDJSON events for the frontend."""
    citations, retrieval_input = _collect_citations(request, db)
    grounded = bool(citations)
    used_documents = len({c.doc_id for c in citations})
    answer_parts: list[str] = []

    yield _encode_stream_event(
        {
            "type": "start",
            "query": request.query,
            "grounded": grounded,
            "used_documents": used_documents,
            "attachment_used": retrieval_input.attachment_used,
            "attachment_file_name": retrieval_input.attachment_file_name,
        }
    )

    try:
        async for chunk in _stream_deepseek(request.query, citations, retrieval_input):
            answer_parts.append(chunk)
            yield _encode_stream_event({"type": "delta", "delta": chunk})

        answer = "".join(answer_parts).strip() or _fallback_answer(citations)
        yield _encode_stream_event(
            {
                "type": "done",
                "query": request.query,
                "answer": answer,
                "citations": [c.model_dump() for c in citations],
                "grounded": grounded,
                "used_documents": used_documents,
                "attachment_used": retrieval_input.attachment_used,
                "attachment_file_name": retrieval_input.attachment_file_name,
            }
        )
    except Exception as exc:
        logger.exception("Grounded chat stream failed")
        yield _encode_stream_event({"type": "error", "detail": str(exc)})
