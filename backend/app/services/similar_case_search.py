"""
Dedicated similar-case comparison flow.

This chain is intentionally isolated from the main chat flow:
1. Read uploaded case materials only from session-scoped temp storage.
2. Detect exact duplicates against indexed documents without persisting uploads.
3. Compare uploaded documents to indexed documents with doc-to-doc similarity.
4. Build a lightweight case search profile from uploaded materials.
5. Blend multiple scores into a final ranking for near-duplicate and similar-case results.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.db_tables import DocumentTable
from app.models.schemas import (
    CaseSearchProfile as CaseSearchProfileSchema,
    ChatCitation,
    SimilarCaseMatchItem,
    SimilarCaseSearchRequest,
    SimilarCaseSearchResponse,
    SessionTempFileKind,
)
from app.services.embedding import encode_query, encode_single
from app.services.parser import ParsedDocument, parse_document
from app.services.retrieval import dual_retrieve, rank_and_aggregate
from app.services.session_files import session_temp_file_store

MIN_SIMILAR_CASE_SCORE = 0.60
MIN_NEAR_DUPLICATE_SCORE = 0.84
DOC_TO_DOC_WEIGHT = 0.40
PARAGRAPH_WEIGHT = 0.20
TEXT_OVERLAP_WEIGHT = 0.17
PORTRAIT_OVERLAP_WEIGHT = 0.18
FILE_NAME_BONUS_WEIGHT = 0.05
MAX_DOC_COMPARE_CHARS = 12000
MAX_KEY_FACTS = 6
MAX_TIMELINE_POINTS = 5
MAX_AMOUNT_TERMS = 5
MAX_FACT_POINTS = 8

_NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)
_DATE_RE = re.compile(r"(?:20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)|(?:\d{1,2}月\d{1,2}日)")
_MONEY_RE = re.compile(r"\d+(?:\.\d+)?(?:元|万元|亿元|%|日|月)")
_CASE_POINT_RE = re.compile(
    r"合同|协议|违约|赔偿|租赁|物业|借款|还款|通知|解除|履行|交付|主体|费用|产权|占有|侵权|劳动|工资|房屋|车位"
)
_SENTENCE_SPLIT_RE = re.compile(r"[，。；：:、\n]")

_RELATIONSHIP_PATTERNS = {
    "物业服务关系": ("物业", "物业费", "车位费", "业主"),
    "借款关系": ("借款", "还款", "利息", "转账"),
    "租赁关系": ("租赁", "租金", "承租", "出租"),
    "买卖合同关系": ("买卖", "货款", "交付", "价款"),
    "劳动关系": ("劳动", "工资", "社保", "解除劳动合同"),
    "侵权责任关系": ("侵权", "损害", "赔偿", "责任"),
    "物权关系": ("产权", "登记", "占有", "返还"),
}

_CLAIM_TARGET_PATTERNS = {
    "物业费": ("物业费",),
    "车位费": ("车位费", "停车费"),
    "违约金": ("违约金",),
    "损害赔偿": ("赔偿", "损失"),
    "返还房屋": ("返还房屋", "腾退"),
    "借款本金": ("借款", "本金"),
    "利息": ("利息",),
    "租金": ("租金",),
}

_PARTY_ROLE_PATTERNS = ("原告", "被告", "业主", "物业公司", "出租人", "承租人", "借款人", "出借人")


@dataclass(slots=True)
class CaseSearchPortrait:
    legal_relationship: str
    dispute_focuses: list[str]
    claim_targets: list[str]
    party_roles: list[str]
    key_facts: list[str]
    timeline: list[str]
    amount_terms: list[str]
    retrieval_intent: str
    comparison_query: str

    def to_schema(self) -> CaseSearchProfileSchema:
        return CaseSearchProfileSchema(
            legal_relationship=self.legal_relationship,
            dispute_focuses=self.dispute_focuses,
            claim_targets=self.claim_targets,
            party_roles=self.party_roles,
            key_facts=self.key_facts,
            timeline=self.timeline,
            amount_terms=self.amount_terms,
            retrieval_intent=self.retrieval_intent,
        )


@dataclass(slots=True)
class UploadedCaseRuntime:
    file_id: str
    file_name: str
    normalized_file_name: str
    normalized_content: str
    text_hash: str
    parsed: ParsedDocument
    document_vector: list[float]
    profile: CaseSearchPortrait


def _normalize_file_name(file_name: str) -> str:
    stem = (file_name or "").strip().lower()
    stem = re.sub(r"\.[a-z0-9]{1,8}$", "", stem)
    return _NON_WORD_RE.sub("", stem)


def _normalize_content(content: str, file_name: str) -> tuple[str, ParsedDocument]:
    parsed = parse_document(content=content, file_name=file_name, source_path=f"session://similar-case/{file_name}")
    normalized = "\n".join(parsed.normalized_lines).strip()
    return normalized, parsed


def _collect_dispute_focuses(parsed: ParsedDocument) -> list[str]:
    counts: dict[str, int] = {}
    for para in parsed.paragraphs:
        for tag in para.dispute_tags:
            counts[tag] = counts.get(tag, 0) + 1
    return [item[0] for item in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:4]]


def _score_fact_paragraph(text: str, dispute_tags: list[str]) -> float:
    score = 0.0
    compact = text.strip()
    if len(compact) < 16:
        return 0.0
    if dispute_tags:
        score += 0.9
    score += min(len(compact) / 280.0, 0.8)
    score += 0.55 * len(_CASE_POINT_RE.findall(compact))
    if _DATE_RE.search(compact):
        score += 0.6
    if _MONEY_RE.search(compact):
        score += 0.5
    return score


def _collect_ranked_points(parsed: ParsedDocument, limit: int) -> list[str]:
    scored: list[tuple[float, str]] = []
    for para in parsed.paragraphs:
        compact = re.sub(r"\s+", " ", (para.content or "").strip())
        score = _score_fact_paragraph(compact, para.dispute_tags)
        if score <= 0:
            continue
        scored.append((score, compact))
    scored.sort(key=lambda item: item[0], reverse=True)

    unique: list[str] = []
    seen = set()
    for _, text in scored:
        if text in seen:
            continue
        seen.add(text)
        unique.append(text[:220])
        if len(unique) >= limit:
            break
    return unique


def _dedupe_keep_order(items: list[str], limit: int | None = None) -> list[str]:
    unique: list[str] = []
    seen = set()
    for item in items:
        compact = re.sub(r"\s+", " ", (item or "").strip())
        if not compact or compact in seen:
            continue
        seen.add(compact)
        unique.append(compact)
        if limit is not None and len(unique) >= limit:
            break
    return unique


def _pick_relationship(normalized_content: str, dispute_focuses: list[str]) -> str:
    lower_text = normalized_content.lower()
    best_name = "未明确"
    best_score = 0
    for name, keywords in _RELATIONSHIP_PATTERNS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in lower_text)
        if any(keyword in " ".join(dispute_focuses) for keyword in keywords):
            score += 1
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _pick_claim_targets(normalized_content: str) -> list[str]:
    lower_text = normalized_content.lower()
    hits: list[str] = []
    for name, keywords in _CLAIM_TARGET_PATTERNS.items():
        if any(keyword.lower() in lower_text for keyword in keywords):
            hits.append(name)
    return hits[:4]


def _pick_party_roles(normalized_content: str) -> list[str]:
    hits = [role for role in _PARTY_ROLE_PATTERNS if role in normalized_content]
    return hits[:4]


def _extract_timeline_points(parsed: ParsedDocument, key_facts: list[str]) -> list[str]:
    timeline = [fact for fact in key_facts if _DATE_RE.search(fact)]
    if not timeline:
        timeline = [line.strip() for line in parsed.normalized_lines if _DATE_RE.search(line)]
    return _dedupe_keep_order(timeline, MAX_TIMELINE_POINTS)


def _extract_amount_terms(normalized_content: str, key_facts: list[str]) -> list[str]:
    candidates: list[str] = []
    for fact in key_facts:
        candidates.extend(_MONEY_RE.findall(fact))
    candidates.extend(_MONEY_RE.findall(normalized_content))
    return _dedupe_keep_order(candidates, MAX_AMOUNT_TERMS)


def _build_comparison_query(profile: CaseSearchPortrait, normalized_content: str) -> str:
    query_parts: list[str] = []
    if profile.legal_relationship and profile.legal_relationship != "未明确":
        query_parts.append(f"法律关系：{profile.legal_relationship}")
    if profile.dispute_focuses:
        query_parts.append(f"争议焦点：{'、'.join(profile.dispute_focuses[:4])}")
    if profile.claim_targets:
        query_parts.append(f"请求标的：{'、'.join(profile.claim_targets[:4])}")
    if profile.party_roles:
        query_parts.append(f"主体角色：{'、'.join(profile.party_roles[:4])}")
    if profile.timeline:
        query_parts.append(f"关键时间：{'；'.join(profile.timeline[:3])}")
    if profile.amount_terms:
        query_parts.append(f"金额/期限：{'、'.join(profile.amount_terms[:4])}")
    if profile.key_facts:
        query_parts.append(f"关键事实：{'；'.join(profile.key_facts[:4])}")
    if profile.retrieval_intent:
        query_parts.append(f"检索要求：{profile.retrieval_intent}")
    return "\n".join(query_parts).strip() or normalized_content[:1800]


def _build_case_search_profile(
    parsed: ParsedDocument,
    normalized_content: str,
    user_query: str,
) -> CaseSearchPortrait:
    dispute_focuses = _collect_dispute_focuses(parsed)
    key_facts = _collect_ranked_points(parsed, MAX_KEY_FACTS)
    if not key_facts:
        key_facts = [line.strip() for line in parsed.normalized_lines if line.strip()][:MAX_KEY_FACTS]
    legal_relationship = _pick_relationship(normalized_content, dispute_focuses)
    claim_targets = _pick_claim_targets(normalized_content)
    party_roles = _pick_party_roles(normalized_content)
    timeline = _extract_timeline_points(parsed, key_facts)
    amount_terms = _extract_amount_terms(normalized_content, key_facts)
    profile = CaseSearchPortrait(
        legal_relationship=legal_relationship,
        dispute_focuses=dispute_focuses,
        claim_targets=claim_targets,
        party_roles=party_roles,
        key_facts=key_facts,
        timeline=timeline,
        amount_terms=amount_terms,
        retrieval_intent=user_query.strip(),
        comparison_query="",
    )
    profile.comparison_query = _build_comparison_query(profile, normalized_content)
    return profile


def _load_uploaded_materials(session_id: str, user_query: str) -> list[UploadedCaseRuntime]:
    records = session_temp_file_store.get_files(session_id=session_id, kind=SessionTempFileKind.CHAT_ATTACHMENT)
    runtimes: list[UploadedCaseRuntime] = []
    for record in records:
        content = (record.content or "").strip()
        if not content:
            continue
        normalized_content, parsed = _normalize_content(content, record.file_name)
        if not normalized_content:
            continue
        profile = _build_case_search_profile(parsed, normalized_content, user_query)
        doc_compare_text = normalized_content[:MAX_DOC_COMPARE_CHARS]
        runtimes.append(
            UploadedCaseRuntime(
                file_id=record.file_id,
                file_name=record.file_name,
                normalized_file_name=_normalize_file_name(record.file_name),
                normalized_content=normalized_content,
                text_hash=hashlib.sha256(normalized_content.encode("utf-8")).hexdigest(),
                parsed=parsed,
                document_vector=encode_single(doc_compare_text),
                profile=profile,
            )
        )
    return runtimes


def _select_primary_runtime(runtimes: list[UploadedCaseRuntime]) -> UploadedCaseRuntime:
    if not runtimes:
        raise HTTPException(status_code=400, detail="No uploaded case materials found for this session")
    return max(runtimes, key=lambda item: len(item.normalized_content))


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    return max(0.0, min(1.0, sum(float(a) * float(b) for a, b in zip(vec_a, vec_b, strict=False))))


def _make_citations_from_lines(doc: DocumentTable, top_lines: list[str], similarity_score: float) -> list[ChatCitation]:
    citations: list[ChatCitation] = []
    content_lines = (doc.normalized_content or "").splitlines()
    for snippet in top_lines[:3]:
        line_start = 1
        line_end = 1
        for idx, line in enumerate(content_lines, start=1):
            if snippet and snippet in line:
                line_start = idx
                line_end = idx
                break
        citations.append(
            ChatCitation(
                doc_id=doc.doc_id,
                file_name=doc.file_name,
                line_start=line_start,
                line_end=line_end,
                version_id=doc.version_id,
                snippet=snippet,
                similarity_score=similarity_score,
            )
        )
    return citations


def _build_exact_match(db: Session, runtime: UploadedCaseRuntime) -> SimilarCaseMatchItem | None:
    doc = db.query(DocumentTable).filter(DocumentTable.normalized_content == runtime.normalized_content).first()
    if not doc:
        return None
    file_name_aligned = _normalize_file_name(doc.file_name) == runtime.normalized_file_name
    matched_points = ["归一化全文完全一致"]
    if file_name_aligned:
        matched_points.append("文件名高度一致")
    return SimilarCaseMatchItem(
        doc_id=doc.doc_id,
        file_name=doc.file_name,
        version_id=doc.version_id,
        final_score=1.0,
        similarity_score=1.0,
        match_type="exact_duplicate",
        match_reason="已命中数据库中的同案/同文档。",
        text_overlap_ratio=1.0,
        file_name_aligned=file_name_aligned,
        citations=_make_citations_from_lines(doc, runtime.profile.key_facts or [runtime.normalized_content[:180]], 1.0),
        matched_points=matched_points,
        matched_profile_fields=[],
    )


def _term_hit_ratio(doc_text: str, terms: list[str]) -> float:
    normalized_terms = _dedupe_keep_order(terms)
    if not normalized_terms:
        return 0.0
    hits = sum(1 for term in normalized_terms if term in doc_text)
    return hits / len(normalized_terms)


def _collect_fact_fragments(key_facts: list[str]) -> list[str]:
    fragments: list[str] = []
    for fact in key_facts[:4]:
        parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(fact) if len(part.strip()) >= 6]
        if parts:
            fragments.extend(parts[:2])
        elif len(fact.strip()) >= 6:
            fragments.append(fact.strip())
    return _dedupe_keep_order([fragment[:32] for fragment in fragments], 8)


def _compute_portrait_overlap(runtime: UploadedCaseRuntime, doc_result, doc_record: DocumentTable) -> tuple[float, list[str]]:
    doc_text = doc_record.normalized_content or ""
    doc_focus_tags = _dedupe_keep_order(
        [tag for para in (doc_result.paragraphs or []) for tag in (para.dispute_tags or [])],
        6,
    )
    doc_relationship = _pick_relationship(doc_text, doc_focus_tags)
    doc_dates = _dedupe_keep_order(_DATE_RE.findall(doc_text), 8)
    doc_amounts = _dedupe_keep_order(_MONEY_RE.findall(doc_text), 8)
    fact_fragments = _collect_fact_fragments(runtime.profile.key_facts)

    score_parts: list[tuple[str, float, float]] = []
    relationship = runtime.profile.legal_relationship.strip()
    if relationship and relationship != "未明确":
        score_parts.append(("法律关系", 0.25, 1.0 if doc_relationship == relationship else 0.0))
    if runtime.profile.dispute_focuses:
        focus_hits = sum(
            1 for focus in runtime.profile.dispute_focuses[:4] if focus in doc_focus_tags or focus in doc_text
        )
        score_parts.append(("争议焦点", 0.24, focus_hits / len(runtime.profile.dispute_focuses[:4])))
    if runtime.profile.claim_targets:
        score_parts.append(("请求标的", 0.18, _term_hit_ratio(doc_text, runtime.profile.claim_targets[:4])))
    if runtime.profile.party_roles:
        score_parts.append(("主体角色", 0.12, _term_hit_ratio(doc_text, runtime.profile.party_roles[:4])))
    if runtime.profile.timeline:
        timeline_hits = sum(1 for point in runtime.profile.timeline[:4] if point in doc_text or point in doc_dates)
        score_parts.append(("关键时间", 0.09, timeline_hits / len(runtime.profile.timeline[:4])))
    if runtime.profile.amount_terms:
        amount_hits = sum(1 for term in runtime.profile.amount_terms[:4] if term in doc_text or term in doc_amounts)
        score_parts.append(("金额期限", 0.07, amount_hits / len(runtime.profile.amount_terms[:4])))
    if fact_fragments:
        score_parts.append(("关键事实", 0.05, _term_hit_ratio(doc_text, fact_fragments)))

    active_weight = sum(weight for _, weight, _ in score_parts)
    if active_weight <= 0:
        return 0.0, []

    weighted_score = sum(weight * score for _, weight, score in score_parts) / active_weight
    matched_fields = [
        label
        for label, _, score in score_parts
        if score >= (0.99 if label == "法律关系" else 0.34)
    ]
    return weighted_score, matched_fields


def _build_similarity_item(
    doc_result,
    doc_record: DocumentTable,
    runtime: UploadedCaseRuntime,
    match_type: str,
) -> SimilarCaseMatchItem:
    doc_text = (doc_record.normalized_content or "").strip()
    text_overlap_ratio = (
        SequenceMatcher(None, runtime.normalized_content[:MAX_DOC_COMPARE_CHARS], doc_text[:MAX_DOC_COMPARE_CHARS]).ratio()
        if doc_text
        else 0.0
    )
    file_name_aligned = _normalize_file_name(doc_record.file_name) == runtime.normalized_file_name
    file_name_bonus = 1.0 if file_name_aligned else 0.0
    doc_to_doc_score = _cosine_similarity(runtime.document_vector, encode_query(doc_text[:MAX_DOC_COMPARE_CHARS] or doc_record.file_name))
    paragraph_score = 0.0
    if doc_result.paragraphs:
        paragraph_score = sum(float(item.similarity_score) for item in doc_result.paragraphs[:3]) / min(len(doc_result.paragraphs[:3]), 3)
    portrait_overlap, matched_profile_fields = _compute_portrait_overlap(runtime, doc_result, doc_record)
    retrieval_score = float(doc_result.similarity_score)

    final_score = (
        DOC_TO_DOC_WEIGHT * doc_to_doc_score
        + PARAGRAPH_WEIGHT * paragraph_score
        + TEXT_OVERLAP_WEIGHT * text_overlap_ratio
        + PORTRAIT_OVERLAP_WEIGHT * portrait_overlap
        + FILE_NAME_BONUS_WEIGHT * file_name_bonus
    )
    final_score = max(final_score, retrieval_score * 0.85)
    final_score = max(0.0, min(1.0, final_score))

    matched_points: list[str] = []
    if file_name_aligned:
        matched_points.append("文件名接近")
    if text_overlap_ratio >= 0.90:
        matched_points.append("正文高度重复")
    elif text_overlap_ratio >= 0.72:
        matched_points.append("正文存在大段重合")
    if portrait_overlap >= 0.62:
        matched_points.append("案件检索画像高度对齐")
    elif portrait_overlap >= 0.42:
        matched_points.append("案件检索画像多字段命中")
    if paragraph_score >= 0.72:
        matched_points.append("关键段落语义接近")
    if doc_to_doc_score >= 0.80:
        matched_points.append("全文文档向量接近")
    if not matched_points:
        matched_points.append("案件画像与事实语义接近")

    if match_type == "near_duplicate":
        reason = "疑似同案不同版本，或同一案件材料的不同排版/OCR版本。"
    else:
        if matched_profile_fields:
            reason = f"案件检索画像中的{'、'.join(matched_profile_fields[:3])}与上传材料接近，且关键段落能相互印证。"
        else:
            reason = "案件检索画像与关键事实段落整体接近。"

    citations = [
        ChatCitation(
            doc_id=para.doc_id,
            file_name=para.citation.file_name,
            line_start=para.citation.line_start,
            line_end=para.citation.line_end,
            version_id=para.citation.version_id,
            snippet=para.snippet,
            similarity_score=float(para.similarity_score),
        )
        for para in doc_result.paragraphs[:3]
    ]

    return SimilarCaseMatchItem(
        doc_id=doc_result.doc_id,
        file_name=doc_result.file_name,
        version_id=doc_result.version_id,
        final_score=final_score,
        similarity_score=retrieval_score,
        match_type=match_type,
        match_reason=reason,
        text_overlap_ratio=text_overlap_ratio,
        file_name_aligned=file_name_aligned,
        citations=citations,
        matched_points=matched_points,
        matched_profile_fields=matched_profile_fields,
    )


async def execute_similar_case_search(request: SimilarCaseSearchRequest, db: Session) -> SimilarCaseSearchResponse:
    session_id = request.session_id.strip()
    runtimes = _load_uploaded_materials(session_id, request.query)
    primary = _select_primary_runtime(runtimes)

    exact_match = _build_exact_match(db, primary)
    comparison_query = primary.profile.comparison_query
    comparison_vector = encode_query(comparison_query)

    doc_hits, para_hits = dual_retrieve(
        query_vector=comparison_vector,
        top_k_documents=max(request.top_k_documents * 3, 10),
        top_k_paragraphs=max(request.top_k_paragraphs, 3),
        dispute_tags=primary.profile.dispute_focuses[:3] or None,
    )
    doc_results = rank_and_aggregate(
        query=comparison_query,
        doc_hits=doc_hits,
        para_hits=para_hits,
        db=db,
        top_k_paragraphs=request.top_k_paragraphs,
    )

    doc_ids = [item.doc_id for item in doc_results]
    doc_map = (
        {item.doc_id: item for item in db.query(DocumentTable).filter(DocumentTable.doc_id.in_(doc_ids)).all()}
        if doc_ids
        else {}
    )

    near_duplicate_matches: list[SimilarCaseMatchItem] = []
    similar_case_matches: list[SimilarCaseMatchItem] = []

    for result in doc_results:
        if exact_match and result.doc_id == exact_match.doc_id:
            continue
        doc_record = doc_map.get(result.doc_id)
        if not doc_record:
            continue

        preview_overlap = (
            SequenceMatcher(
                None,
                primary.normalized_content[:MAX_DOC_COMPARE_CHARS],
                (doc_record.normalized_content or "")[:MAX_DOC_COMPARE_CHARS],
            ).ratio()
            if doc_record.normalized_content
            else 0.0
        )
        file_name_aligned = _normalize_file_name(doc_record.file_name) == primary.normalized_file_name
        is_near_duplicate = (
            preview_overlap >= 0.90
            or (file_name_aligned and preview_overlap >= 0.72)
            or float(result.similarity_score) >= 0.93
        )

        item = _build_similarity_item(
            result,
            doc_record,
            primary,
            "near_duplicate" if is_near_duplicate else "similar_case",
        )

        if is_near_duplicate:
            if item.final_score < MIN_NEAR_DUPLICATE_SCORE:
                continue
            near_duplicate_matches.append(item)
        else:
            if item.final_score < MIN_SIMILAR_CASE_SCORE:
                continue
            similar_case_matches.append(item)

    near_duplicate_matches.sort(key=lambda item: item.final_score, reverse=True)
    similar_case_matches.sort(key=lambda item: item.final_score, reverse=True)

    if exact_match:
        near_duplicate_matches = [item for item in near_duplicate_matches if item.doc_id != exact_match.doc_id]
        similar_case_matches = [item for item in similar_case_matches if item.doc_id != exact_match.doc_id]

    return SimilarCaseSearchResponse(
        session_id=session_id,
        query=request.query,
        comparison_query=comparison_query,
        attachment_file_names=[runtime.file_name for runtime in runtimes],
        case_search_profile=primary.profile.to_schema(),
        extracted_case_points=primary.profile.key_facts,
        exact_match=exact_match,
        near_duplicate_matches=near_duplicate_matches[: request.top_k_documents],
        similar_case_matches=similar_case_matches[: request.top_k_documents],
    )
