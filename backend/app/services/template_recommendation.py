"""
Template recommendation service for contract review sessions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.db_tables import DocumentTable
from app.models.schemas import (
    ReviewTemplateCandidate,
    ReviewTemplateRecommendationResponse,
    SessionTempFileKind,
)
from app.services.embedding import encode_texts
from app.utils.math_helpers import cosine_similarity as _cosine_similarity
from app.services.session_files import session_temp_file_store


CONTRACT_TYPE_KEYWORDS = [
    "劳动",
    "租赁",
    "保密",
    "买卖",
    "采购",
    "服务",
    "借款",
    "委托",
    "居间",
    "施工",
    "装修",
    "物业",
    "房屋买卖",
    "技术开发",
    "技术服务",
    "股权转让",
    "投资",
    "合作",
    "承揽",
    "运输",
    "仓储",
    "代理",
    "加盟",
    "竞业限制",
]

HEADING_KEYWORD_PATTERNS = [
    "付款",
    "价款",
    "期限",
    "保密",
    "违约",
    "争议解决",
    "解除",
    "知识产权",
    "交付",
    "验收",
    "质量",
    "责任",
]

SECTION_LINE_RE = re.compile(
    r"^\s*(第[一二三四五六七八九十百零\d]+条|第[一二三四五六七八九十百零\d]+章|[0-9]+[.、)])"
)


@dataclass(slots=True)
class TemplateProfile:
    doc_id: str
    name: str
    title_tokens: set[str]
    structure_tokens: set[str]
    embedding: list[float]


def _collect_type_tokens(file_name: str, content: str) -> set[str]:
    text = f"{file_name}\n{content[:400]}".replace("合同书", "合同").replace("协议书", "协议")
    return {keyword for keyword in CONTRACT_TYPE_KEYWORDS if keyword in text}


def _collect_structure_tokens(content: str) -> set[str]:
    tokens: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compact = re.sub(r"\s+", "", line)
        if SECTION_LINE_RE.match(compact):
            tokens.add(compact[:20])
        for keyword in HEADING_KEYWORD_PATTERNS:
            if keyword in compact:
                tokens.add(keyword)
    return tokens


def _overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _build_template_profiles(db: Session) -> list[TemplateProfile]:
    rows = (
        db.query(
            DocumentTable.doc_id,
            DocumentTable.file_name,
            DocumentTable.normalized_content,
        )
        .filter(DocumentTable.source_path.like("template://%"))
        .order_by(DocumentTable.updated_at.desc(), DocumentTable.created_at.desc())
        .all()
    )
    if not rows:
        return []

    texts = [str(row.normalized_content or "") for row in rows]
    embeddings = encode_texts([text or row.file_name for row, text in zip(rows, texts)])
    profiles: list[TemplateProfile] = []
    for row, content, embedding in zip(rows, texts, embeddings):
        profiles.append(
            TemplateProfile(
                doc_id=row.doc_id,
                name=row.file_name,
                title_tokens=_collect_type_tokens(row.file_name, content),
                structure_tokens=_collect_structure_tokens(content),
                embedding=embedding,
            )
        )
    return profiles


def _confidence_label(top_score: float, second_score: float | None) -> str:
    margin = top_score - (second_score or 0.0)
    if top_score >= 0.72 and margin >= 0.10:
        return "high"
    if top_score >= 0.55 and margin >= 0.05:
        return "medium"
    return "low"


def _build_reasons(
    semantic_score: float,
    title_score: float,
    structure_score: float,
) -> list[str]:
    reasons: list[str] = []
    if title_score >= 0.5:
        reasons.append("标题或合同类型关键词高度接近")
    elif title_score > 0:
        reasons.append("标题或合同类型关键词存在部分重合")

    if structure_score >= 0.35:
        reasons.append("条款结构与章节关键词重合度较高")
    elif structure_score > 0:
        reasons.append("条款结构存在部分重合")

    if semantic_score >= 0.75:
        reasons.append("全文语义相似度高")
    elif semantic_score >= 0.6:
        reasons.append("全文语义相似度较高")

    if not reasons:
        reasons.append("主要依据全文语义相似度进入候选")
    return reasons[:3]


def recommend_templates_for_session(
    *,
    session_id: str,
    db: Session,
) -> ReviewTemplateRecommendationResponse:
    review_files = session_temp_file_store.get_files(
        session_id=session_id,
        kind=SessionTempFileKind.REVIEW_TARGET,
    )
    if not review_files:
        return ReviewTemplateRecommendationResponse(
            session_id=session_id,
            review_file_count=0,
            recommended_template=None,
            candidate_templates=[],
        )

    template_profiles = _build_template_profiles(db)
    if not template_profiles:
        return ReviewTemplateRecommendationResponse(
            session_id=session_id,
            review_file_count=len(review_files),
            recommended_template=None,
            candidate_templates=[],
        )

    review_vectors = encode_texts([file.content or file.file_name for file in review_files])
    review_type_tokens = [_collect_type_tokens(file.file_name, file.content) for file in review_files]
    review_structure_tokens = [_collect_structure_tokens(file.content) for file in review_files]

    candidates: list[ReviewTemplateCandidate] = []
    for profile in template_profiles:
        semantic_scores = [_cosine_similarity(vector, profile.embedding) for vector in review_vectors]
        title_scores = [_overlap_score(tokens, profile.title_tokens) for tokens in review_type_tokens]
        structure_scores = [_overlap_score(tokens, profile.structure_tokens) for tokens in review_structure_tokens]

        semantic_score = sum(semantic_scores) / len(semantic_scores)
        title_score = sum(title_scores) / len(title_scores)
        structure_score = sum(structure_scores) / len(structure_scores)
        overall_score = semantic_score * 0.6 + title_score * 0.2 + structure_score * 0.2

        candidates.append(
            ReviewTemplateCandidate(
                id=profile.doc_id,
                name=profile.name,
                score=round(overall_score, 4),
                confidence="low",
                semantic_score=round(semantic_score, 4),
                title_score=round(title_score, 4),
                structure_score=round(structure_score, 4),
                reasons=_build_reasons(semantic_score, title_score, structure_score),
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    trimmed = candidates[:5]
    second_score = trimmed[1].score if len(trimmed) > 1 else None
    top = trimmed[0] if trimmed else None

    if top:
        top.confidence = _confidence_label(top.score, second_score)
        for candidate in trimmed[1:]:
            candidate.confidence = _confidence_label(candidate.score, top.score)

    return ReviewTemplateRecommendationResponse(
        session_id=session_id,
        review_file_count=len(review_files),
        recommended_template=top,
        candidate_templates=trimmed,
    )
