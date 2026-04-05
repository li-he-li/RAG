"""
Template-difference contract review core generation service.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, resolve_torch_device
from app.models.db_tables import DocumentTable
from app.models.schemas import SessionTempFileKind
from app.services.embedding import encode_texts
from app.services.parser import parse_document
from app.services.session_files import SessionTempFileRecord, session_temp_file_store

logger = logging.getLogger(__name__)


SECTION_LINE_RE = re.compile(
    r"^\s*(第[一二三四五六七八九十百零\d]+条|第[一二三四五六七八九十百零\d]+章|[0-9]+[.、)])"
)
NUMBER_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?(?:万元|元|%|天|日|个月|月|年)?")

CRITICAL_RISK_KEYWORDS = [
    "违约",
    "赔偿",
    "争议解决",
    "仲裁",
    "管辖",
    "解除",
    "保密",
    "知识产权",
    "自动续期",
    "免责",
    "责任限制",
    "付款",
    "价款",
    "期限",
]


@dataclass(slots=True)
class ClauseUnit:
    clause_id: str
    heading: str
    content: str
    line_start: int
    line_end: int
    heading_tokens: set[str]


@dataclass(slots=True)
class DifferenceFinding:
    category: str
    severity: str
    title: str
    machine_reason: str
    template_excerpt: str
    review_excerpt: str
    score: float


@dataclass(slots=True)
class ContractReviewFileResult:
    file_id: str
    file_name: str
    template_id: str
    template_name: str
    findings: list[DifferenceFinding]
    review_markdown: str


@dataclass(slots=True)
class TemplateContext:
    template_id: str
    template_name: str
    template_content: str
    template_clauses: list[ClauseUnit]


def _encode_stream_event(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _iter_text_chunks(text: str, chunk_size: int = 32) -> list[str]:
    if not text:
        return []
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _clip(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _extract_heading(paragraph_text: str) -> str:
    lines = [line.strip() for line in (paragraph_text or "").splitlines() if line.strip()]
    if not lines:
        return "未命名条款"

    first = lines[0]
    if SECTION_LINE_RE.match(first):
        return first[:40]

    for keyword in CRITICAL_RISK_KEYWORDS:
        if keyword in first:
            return first[:40]
    return first[:32]


def _heading_tokens(text: str) -> set[str]:
    tokens = {keyword for keyword in CRITICAL_RISK_KEYWORDS if keyword in text}
    if SECTION_LINE_RE.match(text):
        tokens.add("section_heading")
    return tokens


def _heading_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / max(1, len(union))


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _extract_number_tokens(text: str) -> set[str]:
    return set(NUMBER_TOKEN_RE.findall(text or ""))


def _contains_critical_keyword(text: str) -> bool:
    return any(keyword in (text or "") for keyword in CRITICAL_RISK_KEYWORDS)


def _segment_clauses(content: str, file_name: str, source_path: str) -> list[ClauseUnit]:
    parsed = parse_document(content=content, file_name=file_name, source_path=source_path)
    clauses: list[ClauseUnit] = []
    for paragraph in parsed.paragraphs:
        if not paragraph.content.strip():
            continue
        heading = _extract_heading(paragraph.content)
        clauses.append(
            ClauseUnit(
                clause_id=paragraph.para_id,
                heading=heading,
                content=paragraph.content.strip(),
                line_start=paragraph.line_start,
                line_end=paragraph.line_end,
                heading_tokens=_heading_tokens(heading + "\n" + paragraph.content[:80]),
            )
        )
    return clauses


def _build_clause_embeddings(clauses: list[ClauseUnit]) -> list[list[float]]:
    if not clauses:
        return []
    texts = [f"{clause.heading}\n{clause.content}" for clause in clauses]
    return encode_texts(texts)


def _build_semantic_similarity_matrix(
    template_embeddings: list[list[float]],
    review_embeddings: list[list[float]],
) -> list[list[float]]:
    if not template_embeddings or not review_embeddings:
        return []
    try:
        import torch
        import torch.nn.functional as F

        device = resolve_torch_device()
        template_tensor = torch.tensor(template_embeddings, dtype=torch.float32, device=device)
        review_tensor = torch.tensor(review_embeddings, dtype=torch.float32, device=device)
        template_tensor = F.normalize(template_tensor, p=2, dim=1)
        review_tensor = F.normalize(review_tensor, p=2, dim=1)
        matrix = torch.matmul(review_tensor, template_tensor.transpose(0, 1))
        matrix = torch.clamp(matrix, min=0.0, max=1.0)
        return matrix.detach().cpu().tolist()
    except Exception:
        logger.debug("Falling back to CPU cosine similarity matrix for contract review", exc_info=True)
        return [
            [_cosine_similarity(review_vector, template_vector) for template_vector in template_embeddings]
            for review_vector in review_embeddings
        ]


def _build_missing_finding(template_clause: ClauseUnit) -> DifferenceFinding:
    severity = "high" if _contains_critical_keyword(template_clause.content) else "medium"
    return DifferenceFinding(
        category="missing_clause",
        severity=severity,
        title=f"缺失模板条款：{template_clause.heading}",
        machine_reason="模板中存在该条款，但待审合同未找到可对齐内容。",
        template_excerpt=_clip(template_clause.content),
        review_excerpt="",
        score=0.0,
    )


def _build_added_clause_finding(review_clause: ClauseUnit, score: float) -> DifferenceFinding:
    severity = "high" if _contains_critical_keyword(review_clause.content) else "medium"
    return DifferenceFinding(
        category="added_clause",
        severity=severity,
        title=f"新增或异常条款：{review_clause.heading}",
        machine_reason="待审合同存在模板中未覆盖的条款，建议人工确认是否引入额外责任或限制。",
        template_excerpt="",
        review_excerpt=_clip(review_clause.content),
        score=round(score, 4),
    )


def _build_changed_clause_finding(
    template_clause: ClauseUnit,
    review_clause: ClauseUnit,
    *,
    score: float,
    semantic_score: float,
    heading_score: float,
) -> DifferenceFinding:
    template_numbers = _extract_number_tokens(template_clause.content)
    review_numbers = _extract_number_tokens(review_clause.content)
    numeric_changed = bool(template_numbers or review_numbers) and template_numbers != review_numbers
    critical = _contains_critical_keyword(template_clause.content) or _contains_critical_keyword(review_clause.content)

    if numeric_changed or (critical and semantic_score < 0.7):
        severity = "high"
    elif semantic_score < 0.78 or heading_score < 0.5:
        severity = "medium"
    else:
        severity = "low"

    reasons: list[str] = []
    if numeric_changed:
        reasons.append("关键数值或期限表达存在变化")
    if heading_score < 0.5:
        reasons.append("条款标题或功能定位偏离模板")
    if semantic_score < 0.78:
        reasons.append("条款语义内容与模板存在明显差异")
    if not reasons:
        reasons.append("条款整体与模板接近，但仍建议人工复核")

    return DifferenceFinding(
        category="changed_clause",
        severity=severity,
        title=f"条款变更：{review_clause.heading}",
        machine_reason="；".join(reasons),
        template_excerpt=_clip(template_clause.content),
        review_excerpt=_clip(review_clause.content),
        score=round(score, 4),
    )


def _select_difference_findings(
    template_clauses: list[ClauseUnit],
    review_clauses: list[ClauseUnit],
) -> list[DifferenceFinding]:
    if not template_clauses and not review_clauses:
        return []
    if not template_clauses:
        return [_build_added_clause_finding(clause, 0.0) for clause in review_clauses[:8]]
    if not review_clauses:
        return [_build_missing_finding(clause) for clause in template_clauses[:8]]

    template_embeddings = _build_clause_embeddings(template_clauses)
    review_embeddings = _build_clause_embeddings(review_clauses)
    semantic_matrix = _build_semantic_similarity_matrix(template_embeddings, review_embeddings)

    matched_template_indices: set[int] = set()
    findings: list[DifferenceFinding] = []

    for review_idx, review_clause in enumerate(review_clauses):
        best_template_idx = -1
        best_semantic = 0.0
        best_heading = 0.0
        best_score = 0.0

        for template_idx, template_clause in enumerate(template_clauses):
            semantic = semantic_matrix[review_idx][template_idx] if semantic_matrix else 0.0
            heading = _heading_overlap(review_clause.heading_tokens, template_clause.heading_tokens)
            overall = semantic * 0.75 + heading * 0.25
            if overall > best_score:
                best_template_idx = template_idx
                best_semantic = semantic
                best_heading = heading
                best_score = overall

        if best_template_idx < 0 or best_score < 0.38:
            if _contains_critical_keyword(review_clause.content) or len(review_clause.content) >= 40:
                findings.append(_build_added_clause_finding(review_clause, best_score))
            continue

        matched_template_indices.add(best_template_idx)
        template_clause = template_clauses[best_template_idx]
        template_numbers = _extract_number_tokens(template_clause.content)
        review_numbers = _extract_number_tokens(review_clause.content)
        numeric_changed = bool(template_numbers or review_numbers) and template_numbers != review_numbers

        if best_semantic < 0.78 or best_heading < 0.5 or numeric_changed:
            findings.append(
                _build_changed_clause_finding(
                    template_clause,
                    review_clause,
                    score=best_score,
                    semantic_score=best_semantic,
                    heading_score=best_heading,
                )
            )

    for template_idx, template_clause in enumerate(template_clauses):
        if template_idx in matched_template_indices:
            continue
        if _contains_critical_keyword(template_clause.content) or len(template_clause.content) >= 40:
            findings.append(_build_missing_finding(template_clause))

    findings.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.severity, 3),
            item.score if item.score else 0.0,
        )
    )
    return findings[:10]


def _fallback_review_markdown(
    *,
    file_name: str,
    template_name: str,
    findings: list[DifferenceFinding],
) -> str:
    if not findings:
        return (
            f"### {file_name}\n"
            f"- 对比模板：{template_name}\n"
            "- 结果：暂未发现明显偏离模板的重点差异，仍建议人工复核关键商业条款。"
        )

    lines = [
        f"### {file_name}",
        f"- 对比模板：{template_name}",
        f"- 发现重点差异：{len(findings)} 项",
        "",
        "#### 重点问题",
    ]
    for finding in findings[:6]:
        lines.append(f"- [{finding.severity}] {finding.title}：{finding.machine_reason}")
    return "\n".join(lines)


def _build_llm_payload(
    *,
    file_name: str,
    template_name: str,
    template_excerpt: str,
    review_excerpt: str,
    findings: list[DifferenceFinding],
) -> dict:
    finding_lines = []
    for idx, finding in enumerate(findings, start=1):
        finding_lines.append(
            {
                "index": idx,
                "category": finding.category,
                "severity": finding.severity,
                "title": finding.title,
                "machine_reason": finding.machine_reason,
                "template_excerpt": finding.template_excerpt,
                "review_excerpt": finding.review_excerpt,
            }
        )

    system_prompt = (
        "你是合同审查助手。"
        "你将收到一个标准模板、一个待审合同，以及程序预定位出的差异候选。"
        "你的任务不是复述候选，而是判断哪些差异构成真实风险，并输出简洁、专业、可执行的中文审查结论。"
        "请严格围绕模板差异作答，不要编造未提供的事实。"
    )
    user_prompt = (
        f"待审文件：{file_name}\n"
        f"标准模板：{template_name}\n\n"
        f"模板摘要：\n{template_excerpt}\n\n"
        f"待审合同摘要：\n{review_excerpt}\n\n"
        "程序识别的差异候选（JSON）：\n"
        f"{json.dumps(finding_lines, ensure_ascii=False, indent=2)}\n\n"
        "请输出 Markdown，结构固定为：\n"
        "1. `#### 审查结论`\n"
        "2. `#### 重点风险`\n"
        "3. `#### 修改建议`\n"
        "要求：\n"
        "- 只列真正有意义的差异\n"
        "- 优先关注违约、价款、期限、解除、争议解决、保密、知识产权、免责等风险\n"
        "- 如果整体接近模板，也要明确说明"
    )

    return {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 900,
    }


async def _generate_review_markdown(
    *,
    file_name: str,
    template_name: str,
    template_content: str,
    review_content: str,
    findings: list[DifferenceFinding],
) -> str:
    fallback = _fallback_review_markdown(
        file_name=file_name,
        template_name=template_name,
        findings=findings,
    )
    if not DEEPSEEK_API_KEY:
        return fallback

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=_build_llm_payload(
                    file_name=file_name,
                    template_name=template_name,
                    template_excerpt=_clip(template_content, 1500),
                    review_excerpt=_clip(review_content, 1500),
                    findings=findings,
                ),
            )
        if response.status_code != 200:
            logger.warning("Contract review llm failed: status=%s body=%s", response.status_code, response.text[:300])
            return fallback
        data = response.json()
        answer = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content", "").strip()
        return answer or fallback
    except Exception as exc:
        logger.warning("Contract review llm request failed: %s", exc)
        return fallback


def _load_template_context(*, template_id: str, db: Session) -> TemplateContext:
    template_row = (
        db.query(
            DocumentTable.doc_id,
            DocumentTable.file_name,
            DocumentTable.normalized_content,
        )
        .filter(DocumentTable.doc_id == template_id)
        .filter(DocumentTable.source_path.like("template://%"))
        .first()
    )
    if not template_row:
        raise ValueError(f"Template {template_id} not found")

    template_name = str(template_row.file_name)
    template_content = str(template_row.normalized_content or "")
    return TemplateContext(
        template_id=str(template_row.doc_id),
        template_name=template_name,
        template_content=template_content,
        template_clauses=_segment_clauses(template_content, template_name, f"template://{template_name}"),
    )


async def _generate_review_file_result(
    *,
    review_file: SessionTempFileRecord,
    template_context: TemplateContext,
    session_id: str,
) -> ContractReviewFileResult:
    review_clauses = _segment_clauses(
        review_file.content,
        review_file.file_name,
        f"session://{session_id}/{review_file.file_id}",
    )
    findings = _select_difference_findings(template_context.template_clauses, review_clauses)
    markdown = await _generate_review_markdown(
        file_name=review_file.file_name,
        template_name=template_context.template_name,
        template_content=template_context.template_content,
        review_content=review_file.content,
        findings=findings,
    )
    return ContractReviewFileResult(
        file_id=review_file.file_id,
        file_name=review_file.file_name,
        template_id=template_context.template_id,
        template_name=template_context.template_name,
        findings=findings,
        review_markdown=markdown,
    )


async def generate_template_difference_review(
    *,
    session_id: str,
    template_id: str,
    db: Session,
) -> list[ContractReviewFileResult]:
    review_files = session_temp_file_store.get_files(
        session_id=session_id,
        kind=SessionTempFileKind.REVIEW_TARGET,
    )
    if not review_files:
        return []

    template_context = _load_template_context(template_id=template_id, db=db)
    results: list[ContractReviewFileResult] = []
    for review_file in review_files:
        results.append(
            await _generate_review_file_result(
                review_file=review_file,
                template_context=template_context,
                session_id=session_id,
            )
        )
    return results


async def stream_template_difference_review(
    *,
    session_id: str,
    template_id: str,
    query: str,
    db: Session,
) -> AsyncIterator[str]:
    review_files = session_temp_file_store.get_files(
        session_id=session_id,
        kind=SessionTempFileKind.REVIEW_TARGET,
    )
    if not review_files:
        yield _encode_stream_event(
            {
                "type": "done",
                "query": query,
                "answer": "当前无合同可审查。请先上传待审合同文件，再发起合同审查。",
                "review_mode": True,
                "template_id": template_id,
                "review_file_count": 0,
            }
        )
        return

    template_context = _load_template_context(template_id=template_id, db=db)
    yield _encode_stream_event(
        {
            "type": "start",
            "query": query,
            "review_mode": True,
            "template_id": template_id,
            "template_name": template_context.template_name,
            "review_file_count": len(review_files),
        }
    )

    try:
        answer_parts: list[str] = []
        for index, review_file in enumerate(review_files, start=1):
            result = await _generate_review_file_result(
                review_file=review_file,
                template_context=template_context,
                session_id=session_id,
            )
            section_text = (result.review_markdown or "").strip()

            yield _encode_stream_event(
                {
                    "type": "file_start",
                    "file_index": index,
                    "file_id": result.file_id,
                    "file_name": result.file_name,
                    "template_id": result.template_id,
                    "template_name": result.template_name,
                    "finding_count": len(result.findings),
                }
            )

            if section_text:
                if answer_parts:
                    separator = "\n\n"
                    answer_parts.append(separator)
                    yield _encode_stream_event({"type": "delta", "delta": separator})

                for chunk in _iter_text_chunks(section_text):
                    answer_parts.append(chunk)
                    yield _encode_stream_event(
                        {
                            "type": "delta",
                            "delta": chunk,
                            "file_index": index,
                            "file_id": result.file_id,
                            "file_name": result.file_name,
                        }
                    )

            yield _encode_stream_event(
                {
                    "type": "file_done",
                    "file_index": index,
                    "file_id": result.file_id,
                    "file_name": result.file_name,
                    "template_id": result.template_id,
                    "template_name": result.template_name,
                    "finding_count": len(result.findings),
                }
            )

        answer = "".join(answer_parts).strip()
        if not answer:
            answer = "当前无合同可审查。请先上传待审合同文件，再发起合同审查。"

        yield _encode_stream_event(
            {
                "type": "done",
                "query": query,
                "answer": answer,
                "review_mode": True,
                "template_id": template_id,
                "template_name": template_context.template_name,
                "review_file_count": len(review_files),
            }
        )
    except Exception as exc:
        logger.exception("Contract review stream failed")
        yield _encode_stream_event({"type": "error", "detail": str(exc)})
