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
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.config import DEBUG, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.models.schemas import ChatCitation, ChatRequest, ChatResponse, SessionTempFileKind
from app.services.attachment_focus import select_attachment_focus
from app.services.embedding import encode_single
from app.services.retrieval import dual_retrieve, rank_and_aggregate, understand_query
from app.services.session_files import session_temp_file_store
from app.services.traceability import validate_and_enrich_results
from app.utils.streaming import encode_stream_event as _encode_stream_event, iter_text_chunks as _iter_text_chunks

logger = logging.getLogger(__name__)

MIN_CITATION_SCORE = 0.45
_NON_RETRIEVAL_TEXT_RE = re.compile(r"[\s\W_]+", re.UNICODE)
_FILE_NAME_SECTION_TITLE = "相关案件文件（数据库命中PDF）"
_NON_RETRIEVAL_QUERIES = {
    "你好",
    "您好",
    "嗨",
    "hello",
    "hi",
    "hey",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "在吗",
    "在嘛",
    "谢谢",
    "感谢",
    "thanks",
    "thankyou",
    "你是谁",
    "你能做什么",
    "你会什么",
    "能再说一遍吗",
    "还有呢",
    "好的",
    "嗯嗯",
    "明白",
    "知道了",
    "继续",
    "然后呢",
}
_NON_RETRIEVAL_PREFIXES = (
    "你好",
    "您好",
    "谢谢",
    "感谢",
    "hello",
    "hi",
    "hey",
)


def _normalize_plain_query(query: str) -> str:
    compact = _NON_RETRIEVAL_TEXT_RE.sub("", (query or "").strip().lower())
    return compact


def _should_skip_retrieval(query: str) -> bool:
    normalized = _normalize_plain_query(query)
    if not normalized:
        return True
    if normalized in _NON_RETRIEVAL_QUERIES:
        return True
    if any(normalized.startswith(prefix) for prefix in _NON_RETRIEVAL_PREFIXES) and len(normalized) <= 12:
        return True
    return False


@dataclass(slots=True)
class ChatRetrievalInput:
    query_text: str
    attachment_used: bool = False
    attachment_file_name: str | None = None
    attachment_overview_summary: str | None = None
    attachment_focus_summary: str | None = None
    attachment_focus_blocks: list[str] | None = None


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

    focus = select_attachment_focus(
        content=attachment_content,
        file_name=latest.file_name,
        query=request.query,
    )
    if not focus:
        return ChatRetrievalInput(query_text=request.query)

    return ChatRetrievalInput(
        query_text=focus.focused_query_text,
        attachment_used=True,
        attachment_file_name=latest.file_name,
        attachment_overview_summary=focus.overview_summary,
        attachment_focus_summary=focus.focus_summary,
        attachment_focus_blocks=[chunk.as_prompt_block() for chunk in focus.focus_chunks],
    )


def _collect_citations(
    request: ChatRequest,
    db: Session,
) -> tuple[list[ChatCitation], ChatRetrievalInput]:
    """Retrieve and flatten citation evidence for a chat query."""
    if _should_skip_retrieval(request.query):
        return [], ChatRetrievalInput(query_text=request.query)

    retrieval_input = _build_attachment_query_input(request)

    def _retrieve_for_query(query_text: str) -> list[ChatCitation]:
        parsed_query = understand_query(query_text, request.dispute_focus)
        query_vector = encode_single(parsed_query["expanded_query"])

        doc_hits, para_hits = dual_retrieve(
            query_vector=query_vector,
            top_k_documents=request.top_k_documents,
            top_k_paragraphs=request.top_k_paragraphs,
            dispute_tags=parsed_query["dispute_tags"],
        )

        doc_results = rank_and_aggregate(
            query=query_text,
            doc_hits=doc_hits,
            para_hits=para_hits,
            db=db,
            top_k_paragraphs=request.top_k_paragraphs,
        )
        doc_results = validate_and_enrich_results(db, doc_results)

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
        filtered = [
            citation
            for score, citation in ranked
            if score >= MIN_CITATION_SCORE and bool((citation.snippet or "").strip())
        ]
        return filtered[: request.top_k_paragraphs]

    try:
        citations = _retrieve_for_query(retrieval_input.query_text)
        # If attachment-focused query misses, retry with raw user query to avoid over-focused drift.
        if (
            not citations
            and retrieval_input.attachment_used
            and retrieval_input.query_text.strip() != request.query.strip()
        ):
            citations = _retrieve_for_query(request.query)
    except Exception as exc:
        logger.exception("Citation retrieval failed, fallback to non-grounded chat: %s", exc)
        return [], ChatRetrievalInput(query_text=request.query)

    return citations, retrieval_input


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


def _collect_related_file_names(citations: list[ChatCitation], *, limit: int = 8) -> list[str]:
    score_by_file_name: dict[str, float] = {}
    for citation in citations:
        file_name = (citation.file_name or "").strip()
        if not file_name:
            continue
        score = max(float(citation.similarity_score), 0.0)
        prev = score_by_file_name.get(file_name)
        if prev is None or score > prev:
            score_by_file_name[file_name] = score

    ranked = sorted(score_by_file_name.items(), key=lambda item: (-item[1], item[0]))
    return [file_name for file_name, _score in ranked[:limit]]


def _build_related_file_name_block(citations: list[ChatCitation]) -> str:
    file_names = _collect_related_file_names(citations)
    if not file_names:
        return ""
    lines = [_FILE_NAME_SECTION_TITLE + "："]
    lines.extend(f"{idx}. {name}" for idx, name in enumerate(file_names, start=1))
    return "\n".join(lines)


def _prepend_related_file_names(answer: str, citations: list[ChatCitation]) -> str:
    text = (answer or "").strip()
    block = _build_related_file_name_block(citations)
    if not block:
        return text
    if _FILE_NAME_SECTION_TITLE in text:
        return text
    if not text:
        return block
    return f"{block}\n\n{text}"


def _fallback_answer(citations: list[ChatCitation], *, query: str = "") -> str:
    """Deterministic fallback when DeepSeek is unavailable."""
    if not citations:
        return (
            "当前知识库没有命中证据，且 DeepSeek 服务暂不可用。"
            "请稍后重试，或先上传相关文档后再提问。"
        )

    lines = ["DeepSeek 暂不可用。"]
    file_names = _collect_related_file_names(citations)
    if file_names:
        lines.append(_FILE_NAME_SECTION_TITLE + "：")
        for idx, file_name in enumerate(file_names, start=1):
            lines.append(f"{idx}. {file_name}")
    else:
        lines.append("未能从当前证据稳定识别数据库文件名。")

    if query:
        lines.append("")
        lines.append(f"围绕你的问题“{query}”的证据线索：")

    for c in citations[:3]:
        snippet = c.snippet.replace("\n", " ").strip()
        if len(snippet) > 140:
            snippet = snippet[:140] + "..."
        lines.append(f"- {c.file_name} 第{c.line_start}-{c.line_end}行（v{c.version_id}）：{snippet}")
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
        file_name_hints = _build_related_file_name_block(citations)
        response_rules = (
            "回答必须以用户问题为主导，不要偏离用户问题扩写。"
            "先输出“相关案件文件（数据库命中PDF）”小节，直接逐条列出 file_name 原文；"
            "禁止先按纠纷类型分组，也不要先写与问题无关的泛化总结。"
            "随后输出“围绕问题的回答”小节，先给结论再给依据，并标注证据编号。"
        )
        if retrieval_input.attachment_used and retrieval_input.attachment_focus_summary:
            system_prompt = (
                "你是法律类案检索对比助手。你需要同时参考用户上传的原案件材料和给定数据库证据回答。"
                "不要忽略原案件内容，也不要编造事实。"
                "请明确说明候选案例与原案件的相似点、差异点，以及你判断相似的原因。"
                "引用数据库证据时请标注证据编号，如 [1][2]。"
                f"{response_rules}"
            )
            user_prompt = (
                f"用户问题：{query}\n\n"
                f"用户上传的原案件材料（文件：{retrieval_input.attachment_file_name or '未命名附件'}）整体摘要：\n"
                f"{retrieval_input.attachment_overview_summary or retrieval_input.attachment_focus_summary}\n\n"
                "用户上传案件的重点摘要：\n"
                f"{retrieval_input.attachment_focus_summary}\n\n"
                + (
                    f"数据库命中的文件名线索（请按原文照抄）：\n{file_name_hints}\n\n"
                    if file_name_hints
                    else ""
                )
                + (
                    "请务必先直接列出数据库命中的PDF文件名，再围绕用户问题回答，不要按纠纷类型分组。\n\n"
                )
                + (
                "数据库检索到的候选证据如下：\n"
                f"{evidence_context}\n\n"
                "请基于原案件材料与候选证据进行回答，至少覆盖：\n"
                "1. 哪些案例与原案件更相似\n"
                "2. 相似主要体现在哪些事实或争议点\n"
                "3. 如果证据不足以支持强对比，要明确指出不足"
                )
            )
        else:
            system_prompt = (
                "你是法律检索问答助手。你只能依据给定数据库证据回答，"
                "不要编造事实。关键结论后请标注证据编号，如 [1][2]。"
                f"{response_rules}"
            )
            user_prompt = (
                f"用户问题：{query}\n\n"
                + (
                    f"数据库命中的文件名线索（请按原文照抄）：\n{file_name_hints}\n\n"
                    if file_name_hints
                    else ""
                )
                + "请先直接列出数据库命中的PDF文件名，再围绕用户问题回答；不要按纠纷类型分组。\n\n"
                + (
                "可用证据如下：\n"
                f"{evidence_context}\n\n"
                "请给出简明答案并附证据编号。"
                )
            )
        temperature = 0.1
    else:
        if retrieval_input.attachment_used and retrieval_input.attachment_focus_summary:
            system_prompt = (
                "你是法律类案检索助手。当前知识库没有命中可引用案例证据。"
                "你可以参考用户上传的原案件材料说明当前无法完成强相似案例对比，"
                "但不要把没有证据支撑的内容说成数据库结论。"
            )
            user_prompt = (
                f"用户问题：{query}\n\n"
                f"用户上传的原案件材料整体摘要（文件：{retrieval_input.attachment_file_name or '未命名附件'}）：\n"
                f"{retrieval_input.attachment_overview_summary or retrieval_input.attachment_focus_summary}\n\n"
                "用户上传案件的重点摘要：\n"
                f"{retrieval_input.attachment_focus_summary}\n\n"
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
        "messages": _assemble_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            history_messages=[],
        ),
        "temperature": temperature,
        "max_tokens": 700,
    }
    if stream:
        payload["stream"] = True
    return payload


def _assemble_messages(
    *,
    system_prompt: str,
    user_prompt: str,
    history_messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Assemble messages array: [system, ...history, user]."""
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history_messages:
        messages.append(msg)
    messages.append({"role": "user", "content": user_prompt})
    return messages


def build_memory_aware_payload(
    *,
    system_prompt: str,
    user_prompt: str,
    history_messages: list[dict[str, str]],
    temperature: float = 0.3,
    stream: bool = False,
) -> dict:
    """Build DeepSeek payload with conversation history injected."""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": _assemble_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            history_messages=history_messages,
        ),
        "temperature": temperature,
        "max_tokens": 700,
    }
    if stream:
        payload["stream"] = True
    return payload


CASUAL_SYSTEM_PROMPT = (
    "你是一个友好的法律助手。你可以轻松地闲聊，也可以回答法律问题。"
    "如果用户问法律问题，请基于你的知识给出建议，并建议用户上传相关文档获取精确答案。"
    "保持对话自然流畅。"
)


async def handle_casual_chat(
    query: str,
    *,
    history_messages: list[dict[str, str]] | None = None,
    stream: bool = False,
) -> str:
    """Handle casual chat using memory context, no retrieval pipeline."""
    if not DEEPSEEK_API_KEY:
        return "你好！我是法律助手，有什么可以帮你的？"

    payload = build_memory_aware_payload(
        system_prompt=CASUAL_SYSTEM_PROMPT,
        user_prompt=query,
        history_messages=history_messages or [],
        temperature=0.5,
        stream=stream,
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.exception("Casual chat failed: %s", exc)
        return "抱歉，我暂时无法回复，请稍后再试。"


async def _ask_deepseek(query: str, citations: list[ChatCitation], retrieval_input: ChatRetrievalInput) -> str:
    """Ask DeepSeek, grounded when evidence exists, general otherwise."""
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY is empty, using fallback answer")
        return _fallback_answer(citations, query=query)

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
        return _fallback_answer(citations, query=query)

    if resp.status_code != 200:
        if DEBUG:
            logger.warning("DeepSeek chat failed: status=%s body=%s", resp.status_code, resp.text[:300])
        else:
            logger.warning("DeepSeek chat failed: status=%s", resp.status_code)
        return _fallback_answer(citations, query=query)

    try:
        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        if answer:
            return _prepend_related_file_names(answer, citations)
    except Exception as exc:
        logger.warning("DeepSeek response parsing failed: %s", exc)

    return _prepend_related_file_names(_fallback_answer(citations, query=query), citations)


async def _stream_deepseek(
    query: str,
    citations: list[ChatCitation],
    retrieval_input: ChatRetrievalInput,
) -> AsyncIterator[str]:
    """Stream DeepSeek answer tokens, falling back to chunked local text when needed."""
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY is empty, using fallback answer")
        for chunk in _iter_text_chunks(_fallback_answer(citations, query=query)):
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
                    if DEBUG:
                        logger.warning("DeepSeek stream failed: status=%s body=%s", resp.status_code, body[:300])
                    else:
                        logger.warning("DeepSeek stream failed: status=%s", resp.status_code)
                    for chunk in _iter_text_chunks(_fallback_answer(citations, query=query)):
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

    for chunk in _iter_text_chunks(_fallback_answer(citations, query=query)):
        yield chunk


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

        answer = "".join(answer_parts).strip() or _fallback_answer(citations, query=request.query)
        answer = _prepend_related_file_names(answer, citations)
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
        from app.core.http_errors import internal_error_detail
        yield _encode_stream_event({"type": "error", "detail": internal_error_detail(exc)})
