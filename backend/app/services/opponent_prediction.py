"""
Opponent-prediction flow with user-question alignment:
1. Build base case profile from the selected prediction template.
2. Infer the user's actual prediction intent from the natural-language query.
3. Run intent-constrained retrieval from the opponent's perspective.
4. Build candidate opponent arguments.
5. Re-rank and reshape the result so the final answer matches the user's ask.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.models.db_tables import (
    PredictionReportSnapshotTable,
    PredictionTemplateAssetParagraphTable,
    PredictionTemplateAssetTable,
    PredictionTemplateTable,
)
from app.models.schemas import (
    ChatCitation,
    OpponentPredictionReport,
    PredictedArgument,
    SearchRequest,
)
from app.services.prediction_templates import validate_prediction_template_ready
from app.services.retrieval import execute_search
from app.services.traceability import validate_and_enrich_results


logger = logging.getLogger(__name__)

DATE_RE = re.compile(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)|(\d{1,2}月\d{1,2}日)")
AMOUNT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:元|万元|亿元|%|天|个月)")
LINE_SPLIT_RE = re.compile(r"[，。；\n]")

STRONG_FACT_KEYWORDS = (
    "签订",
    "约定",
    "支付",
    "交付",
    "履行",
    "违约",
    "解除",
    "通知",
    "逾期",
    "拒绝",
    "催告",
    "损失",
    "赔偿",
    "借款",
    "还款",
    "租赁",
    "物业",
)

NEGATION_HINTS = ("不同意", "不认可", "不存在", "不应", "无需", "不能", "无权", "未", "拒绝", "抗辩")

FOCUS_QUERY_HINTS = {
    "合同违约": "对方抗辩 违约责任 合同解释 构成要件",
    "损害赔偿": "对方抗辩 损失计算 因果关系 举证责任",
    "债务纠纷": "对方抗辩 借款事实 还款证明 金额争议",
    "劳动争议": "对方抗辩 劳动关系 工资加班 举证责任",
    "房产纠纷": "对方抗辩 占有使用 物业费用 合同解释",
    "程序事项": "对方抗辩 诉讼时效 管辖 送达 程序瑕疵",
}

QUESTION_TYPE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("rebuttal-angle", ("角度", "从什么角度", "如何辩驳", "怎么辩驳", "辩驳路径", "辩驳思路")),
    ("evidence-attack", ("证据", "攻击哪条证据", "证据漏洞", "举证漏洞", "证据薄弱点")),
    ("procedure-attack", ("程序", "程序上", "管辖", "诉讼时效", "送达", "程序抗辩")),
    ("strongest-point", ("最强", "最有力", "最大概率", "核心抗辩", "主打")),
    ("sequence-strategy", ("顺序", "先后", "第一步", "第二步", "打法", "策略")),
]


@dataclass(slots=True)
class PredictionIntent:
    question_type: str
    focus_dimension: str
    target_scope: str
    answer_shape: str
    ranking_mode: str
    answer_title: str
    answer_summary: str
    retrieval_hints: list[str]


@dataclass(slots=True)
class PredictionCaseProfile:
    case_name: str
    user_goal: str
    party_roles: list[str]
    legal_relationship: str
    dispute_focuses: list[str]
    known_facts: list[str]
    timeline: list[str]
    claim_targets: list[str]
    core_conflicts: list[str]
    existing_evidence: list[str]
    missing_information: list[str]
    opponent_favorable_points: list[str]


@dataclass(slots=True)
class CandidateCaseSignals:
    case_name: str
    user_goal: str
    candidate_focuses: list[str]
    candidate_facts: list[str]
    candidate_timeline: list[str]
    candidate_party_roles: list[str]
    candidate_claim_targets: list[str]
    candidate_conflicts: list[str]
    candidate_missing_information: list[str]
    candidate_opponent_points: list[str]
    candidate_legal_relationship: str
    existing_evidence: list[str]


@dataclass(slots=True)
class RetrievalBundle:
    citations: list[ChatCitation]
    summaries: list[str]
    search_queries: list[str]


RELATIONSHIP_HINTS = {
    "合同违约": "合同履行关系",
    "损害赔偿": "侵权或损害赔偿关系",
    "债务纠纷": "借贷或债务清偿关系",
    "劳动争议": "劳动用工关系",
    "房产纠纷": "房产占有、使用或物业服务关系",
    "程序事项": "诉讼程序关系",
}


def _load_prediction_template_or_404(db: Session, template_id: str) -> PredictionTemplateTable:
    template = (
        db.query(PredictionTemplateTable)
        .filter(PredictionTemplateTable.template_id == template_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail=f"Prediction template {template_id} not found")
    return template


def _load_template_assets(db: Session, template_id: str) -> list[PredictionTemplateAssetTable]:
    return (
        db.query(PredictionTemplateAssetTable)
        .filter(PredictionTemplateAssetTable.template_id == template_id)
        .order_by(PredictionTemplateAssetTable.created_at.asc())
        .all()
    )


def _load_template_paragraphs(
    db: Session,
    template_id: str,
) -> list[tuple[PredictionTemplateAssetParagraphTable, PredictionTemplateAssetTable]]:
    return (
        db.query(PredictionTemplateAssetParagraphTable, PredictionTemplateAssetTable)
        .join(
            PredictionTemplateAssetTable,
            PredictionTemplateAssetTable.asset_id == PredictionTemplateAssetParagraphTable.asset_id,
        )
        .filter(PredictionTemplateAssetParagraphTable.template_id == template_id)
        .order_by(
            PredictionTemplateAssetTable.created_at.asc(),
            PredictionTemplateAssetParagraphTable.line_start.asc(),
        )
        .all()
    )


def _compact(text: str, limit: int = 220) -> str:
    collapsed = re.sub(r"\s+", " ", (text or "")).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


def _extract_focuses(paragraphs: list[tuple[PredictionTemplateAssetParagraphTable, PredictionTemplateAssetTable]]) -> list[str]:
    counter: Counter[str] = Counter()
    for paragraph, _asset in paragraphs:
        tags = [tag.strip() for tag in (paragraph.dispute_tags or "").split(",") if tag.strip()]
        counter.update(tags)
    if counter:
        return [tag for tag, _count in counter.most_common(3)]
    return ["程序事项"]


def _extract_facts(paragraphs: list[tuple[PredictionTemplateAssetParagraphTable, PredictionTemplateAssetTable]]) -> list[str]:
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for paragraph, _asset in paragraphs:
        content = _compact(paragraph.content or "", limit=180)
        if not content or content in seen:
            continue
        score = 0
        if DATE_RE.search(content):
            score += 2
        if AMOUNT_RE.search(content):
            score += 2
        if any(keyword in content for keyword in STRONG_FACT_KEYWORDS):
            score += 3
        if len(content) >= 30:
            score += 1
        seen.add(content)
        scored.append((score, content))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [content for score, content in scored if score > 0][:6]


def _extract_timeline(facts: list[str]) -> list[str]:
    timeline = [fact for fact in facts if DATE_RE.search(fact)]
    return timeline[:4]


def _extract_opponent_favorable_points(
    paragraphs: list[tuple[PredictionTemplateAssetParagraphTable, PredictionTemplateAssetTable]],
) -> list[str]:
    explicit: list[str] = []
    fallback: list[str] = []
    for paragraph, asset in paragraphs:
        if asset.asset_kind != "opponent_corpus":
            continue
        content = _compact(paragraph.content or "", limit=180)
        if not content:
            continue
        fallback.append(content)
        if any(token in content for token in NEGATION_HINTS):
            explicit.append(content)
    return (explicit or fallback)[:4]


def _extract_missing_information(
    assets: list[PredictionTemplateAssetTable],
    facts: list[str],
    timeline: list[str],
) -> list[str]:
    missing: list[str] = []
    has_amount = any(AMOUNT_RE.search(fact) for fact in facts)
    has_opponent_corpus = any(asset.asset_kind == "opponent_corpus" for asset in assets)
    if not timeline:
        missing.append("关键时间线仍不够清楚，对方容易把争议转成事实发生顺序不明。")
    if not has_amount:
        missing.append("金额、费用口径或计算基准不够明确，容易被对方攻击请求依据。")
    if not has_opponent_corpus:
        missing.append("尚未上传对方语料，对对方既有表述和抗辩口径的判断会更保守。")
    if not facts:
        missing.append("案情材料尚未形成稳定事实摘要，仍需补充核心事实。")
    return missing[:4]


def _default_legal_relationship(dispute_focuses: list[str]) -> str:
    for focus in dispute_focuses:
        if focus in RELATIONSHIP_HINTS:
            return RELATIONSHIP_HINTS[focus]
    return "待进一步识别的法律关系"


def _extract_party_roles(assets: list[PredictionTemplateAssetTable], facts: list[str]) -> list[str]:
    role_hints: list[str] = []
    combined = " ".join([asset.file_name for asset in assets] + facts[:4])
    role_patterns = [
        ("原告/被告", ("原告", "被告")),
        ("甲方/乙方", ("甲方", "乙方")),
        ("出借人/借款人", ("出借", "借款")),
        ("出租人/承租人", ("出租", "承租")),
        ("物业公司/业主", ("物业", "业主")),
        ("用人单位/劳动者", ("公司", "员工")),
    ]
    for label, tokens in role_patterns:
        if all(token in combined for token in tokens):
            role_hints.append(label)
    if not role_hints:
        role_hints.append("我方/对方")
    return role_hints[:3]


def _extract_claim_targets(facts: list[str], dispute_focuses: list[str], query: str) -> list[str]:
    text = " ".join(facts[:6] + dispute_focuses + [query])
    candidates = [
        ("物业费", ("物业费", "物业服务费")),
        ("车位费", ("车位费", "停车费")),
        ("违约金", ("违约金",)),
        ("损害赔偿", ("赔偿", "损失")),
        ("借款本金", ("借款", "本金")),
        ("利息", ("利息",)),
        ("租金", ("租金", "租赁费")),
        ("工资报酬", ("工资", "报酬")),
    ]
    targets: list[str] = []
    for label, tokens in candidates:
        if any(token in text for token in tokens):
            targets.append(label)
    if not targets and dispute_focuses:
        targets.append(dispute_focuses[0])
    return targets[:4]


def _extract_core_conflicts(
    dispute_focuses: list[str],
    facts: list[str],
    opponent_points: list[str],
    missing_information: list[str],
) -> list[str]:
    conflicts: list[str] = []
    if dispute_focuses:
        conflicts.extend(dispute_focuses[:2])
    for fact in facts[:3]:
        sentence = LINE_SPLIT_RE.split(fact)[0].strip()
        if sentence:
            conflicts.append(sentence)
    for point in opponent_points[:2]:
        sentence = LINE_SPLIT_RE.split(point)[0].strip()
        if sentence:
            conflicts.append(sentence)
    if missing_information:
        conflicts.append(missing_information[0])
    deduped: list[str] = []
    seen: set[str] = set()
    for item in conflicts:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:5]


def _score_profile_passage(content: str, *, asset_kind: str) -> int:
    score = 0
    if DATE_RE.search(content):
        score += 2
    if AMOUNT_RE.search(content):
        score += 2
    if any(keyword in content for keyword in STRONG_FACT_KEYWORDS):
        score += 3
    if asset_kind == "opponent_corpus" and any(token in content for token in NEGATION_HINTS):
        score += 4
    if len(content) >= 30:
        score += 1
    return score


def _select_profile_passages(
    paragraphs: list[tuple[PredictionTemplateAssetParagraphTable, PredictionTemplateAssetTable]],
    *,
    asset_kind: str,
    limit: int,
) -> list[str]:
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for paragraph, asset in paragraphs:
        if asset.asset_kind != asset_kind:
            continue
        content = _compact(paragraph.content or "", limit=220)
        if not content or content in seen:
            continue
        seen.add(content)
        ranked.append((_score_profile_passage(content, asset_kind=asset_kind), content))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [content for score, content in ranked if score > 0][:limit]


def _build_candidate_case_signals(
    *,
    template: PredictionTemplateTable,
    assets: list[PredictionTemplateAssetTable],
    paragraphs: list[tuple[PredictionTemplateAssetParagraphTable, PredictionTemplateAssetTable]],
    query: str,
) -> CandidateCaseSignals:
    dispute_focuses = _extract_focuses(paragraphs)
    facts = _extract_facts(paragraphs)
    timeline = _extract_timeline(facts)
    missing_information = _extract_missing_information(assets, facts, timeline)
    opponent_favorable_points = _extract_opponent_favorable_points(paragraphs)
    return CandidateCaseSignals(
        case_name=template.case_name,
        user_goal=query.strip(),
        candidate_party_roles=_extract_party_roles(assets, facts),
        candidate_legal_relationship=_default_legal_relationship(dispute_focuses),
        candidate_focuses=dispute_focuses,
        candidate_facts=facts,
        candidate_timeline=timeline,
        candidate_claim_targets=_extract_claim_targets(facts, dispute_focuses, query),
        candidate_conflicts=_extract_core_conflicts(
            dispute_focuses,
            facts,
            opponent_favorable_points,
            missing_information,
        ),
        existing_evidence=[asset.file_name for asset in assets],
        candidate_missing_information=missing_information,
        candidate_opponent_points=opponent_favorable_points,
    )


async def _generate_case_profile_with_llm(
    *,
    signals: CandidateCaseSignals,
    case_material_passages: list[str],
    opponent_passages: list[str],
) -> dict[str, Any] | None:
    if not DEEPSEEK_API_KEY:
        return None

    payload = {
        "case_name": signals.case_name,
        "user_goal": signals.user_goal,
        "candidate_signals": {
            "party_roles": signals.candidate_party_roles,
            "legal_relationship": signals.candidate_legal_relationship,
            "dispute_focuses": signals.candidate_focuses,
            "known_facts": signals.candidate_facts,
            "timeline": signals.candidate_timeline,
            "claim_targets": signals.candidate_claim_targets,
            "core_conflicts": signals.candidate_conflicts,
            "missing_information": signals.candidate_missing_information,
            "opponent_favorable_points": signals.candidate_opponent_points,
        },
        "existing_evidence": signals.existing_evidence,
        "case_material_passages": case_material_passages,
        "opponent_corpus_passages": opponent_passages,
    }
    system_prompt = (
        "你是法律案件画像整理助手。你的任务不是输出最终预测，而是把零散材料重构成高质量案件画像。"
        "你会收到一组候选线索，它们只是启发，不是最终结论。真正的争议焦点、关键事实、时间线和对方有利点，都必须由你综合原始片段后重新判断。"
        "请严格输出 JSON，对字段做精炼归纳，不能空泛。"
        "格式为："
        "{\"party_roles\":[],\"legal_relationship\":\"\",\"dispute_focuses\":[],\"known_facts\":[],"
        "\"timeline\":[],\"claim_targets\":[],\"core_conflicts\":[],\"missing_information\":[],\"opponent_favorable_points\":[]}"
        "要求："
        "known_facts 保留最关键的 4-6 条；timeline 要按时间顺序；"
        "core_conflicts 要写成真正影响攻防的核心矛盾；"
        "opponent_favorable_points 只保留对对方真的有利的点；"
        "如果候选线索和原始片段冲突，以你基于原始片段的综合判断为准；"
        "如果信息不足就明确保守归纳，不要编造。"
    )
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1200,
                },
            )
        if response.status_code != 200:
            logger.warning("Case-profile LLM failed: status=%s body=%s", response.status_code, response.text[:300])
            return None
        content = (((response.json().get("choices") or [{}])[0]).get("message") or {}).get("content", "")
        parsed = _extract_json_object(content)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        logger.exception("Case-profile LLM generation failed")
        return None


def _pick_list(raw: Any, fallback: list[str], limit: int) -> list[str]:
    if not isinstance(raw, list):
        return fallback[:limit]
    items = [str(item).strip() for item in raw if str(item).strip()]
    return items[:limit] or fallback[:limit]


def _pick_str(raw: Any, fallback: str) -> str:
    value = str(raw).strip() if raw is not None else ""
    return value or fallback


async def build_case_profile(
    db: Session,
    *,
    template_id: str,
    query: str,
) -> PredictionCaseProfile:
    template = _load_prediction_template_or_404(db, template_id)
    assets = _load_template_assets(db, template_id)
    paragraphs = _load_template_paragraphs(db, template_id)
    candidate_signals = _build_candidate_case_signals(
        template=template,
        assets=assets,
        paragraphs=paragraphs,
        query=query,
    )

    case_material_passages = _select_profile_passages(paragraphs, asset_kind="case_material", limit=8)
    opponent_passages = _select_profile_passages(paragraphs, asset_kind="opponent_corpus", limit=6)
    refined = await _generate_case_profile_with_llm(
        signals=candidate_signals,
        case_material_passages=case_material_passages,
        opponent_passages=opponent_passages,
    )
    if not refined:
        return PredictionCaseProfile(
            case_name=candidate_signals.case_name,
            user_goal=candidate_signals.user_goal,
            party_roles=candidate_signals.candidate_party_roles,
            legal_relationship=candidate_signals.candidate_legal_relationship,
            dispute_focuses=candidate_signals.candidate_focuses,
            known_facts=candidate_signals.candidate_facts,
            timeline=candidate_signals.candidate_timeline,
            claim_targets=candidate_signals.candidate_claim_targets,
            core_conflicts=candidate_signals.candidate_conflicts,
            existing_evidence=candidate_signals.existing_evidence,
            missing_information=candidate_signals.candidate_missing_information,
            opponent_favorable_points=candidate_signals.candidate_opponent_points,
        )

    return PredictionCaseProfile(
        case_name=candidate_signals.case_name,
        user_goal=candidate_signals.user_goal,
        party_roles=_pick_list(refined.get("party_roles"), candidate_signals.candidate_party_roles, 4),
        legal_relationship=_pick_str(refined.get("legal_relationship"), candidate_signals.candidate_legal_relationship),
        dispute_focuses=_pick_list(refined.get("dispute_focuses"), candidate_signals.candidate_focuses, 4),
        known_facts=_pick_list(refined.get("known_facts"), candidate_signals.candidate_facts, 6),
        timeline=_pick_list(refined.get("timeline"), candidate_signals.candidate_timeline, 5),
        claim_targets=_pick_list(refined.get("claim_targets"), candidate_signals.candidate_claim_targets, 5),
        core_conflicts=_pick_list(refined.get("core_conflicts"), candidate_signals.candidate_conflicts, 5),
        existing_evidence=candidate_signals.existing_evidence,
        missing_information=_pick_list(refined.get("missing_information"), candidate_signals.candidate_missing_information, 5),
        opponent_favorable_points=_pick_list(
            refined.get("opponent_favorable_points"),
            candidate_signals.candidate_opponent_points,
            5,
        ),
    )


def infer_prediction_intent(query: str) -> PredictionIntent:
    cleaned = re.sub(r"\s+", " ", (query or "")).strip()
    lowered = cleaned.lower()
    question_type = "general-opponent-view"
    for candidate, patterns in QUESTION_TYPE_PATTERNS:
        if any(pattern in cleaned or pattern in lowered for pattern in patterns):
            question_type = candidate
            break

    if question_type == "rebuttal-angle":
        return PredictionIntent(
            question_type=question_type,
            focus_dimension="辩驳角度",
            target_scope="opponent",
            answer_shape="angle-list",
            ranking_mode="breadth-first",
            answer_title="对方可能采取的辩驳角度",
            answer_summary="优先展示对方可能从哪些层面组织辩驳，再补每个角度下的具体抓手。",
            retrieval_hints=["抗辩角度", "程序抗辩", "实体抗辩", "证据攻击"],
        )
    if question_type == "evidence-attack":
        return PredictionIntent(
            question_type=question_type,
            focus_dimension="证据攻击点",
            target_scope="opponent",
            answer_shape="evidence-attack-list",
            ranking_mode="weakness-first",
            answer_title="对方可能优先攻击的证据点",
            answer_summary="优先指出最容易被对方抓住的证据或举证漏洞，并补充补强建议。",
            retrieval_hints=["证据不足", "举证责任", "证据攻击", "真实性合法性关联性"],
        )
    if question_type == "procedure-attack":
        return PredictionIntent(
            question_type=question_type,
            focus_dimension="程序抗辩",
            target_scope="opponent",
            answer_shape="procedure-list",
            ranking_mode="priority-first",
            answer_title="对方可能先打的程序层抗辩",
            answer_summary="聚焦程序性阻断点，如时效、管辖、送达和主体资格，而不是泛泛展开实体争议。",
            retrieval_hints=["诉讼时效", "管辖异议", "主体资格", "送达程序"],
        )
    if question_type == "strongest-point":
        return PredictionIntent(
            question_type=question_type,
            focus_dimension="最强抗辩点",
            target_scope="opponent",
            answer_shape="top-ranked-list",
            ranking_mode="strength-first",
            answer_title="对方最可能主打的抗辩点",
            answer_summary="按攻击力和可证成度排序，只保留最可能被主打的几个点。",
            retrieval_hints=["核心抗辩", "最强抗辩", "主打观点", "关键争议"],
        )
    if question_type == "sequence-strategy":
        return PredictionIntent(
            question_type=question_type,
            focus_dimension="打法顺序",
            target_scope="opponent",
            answer_shape="sequence-list",
            ranking_mode="sequence-first",
            answer_title="对方可能采用的攻防顺序",
            answer_summary="强调先打什么、后打什么，以及各步骤之间的衔接，而不是平铺观点。",
            retrieval_hints=["抗辩顺序", "先程序后实体", "打法顺序", "阶段性抗辩"],
        )

    return PredictionIntent(
        question_type=question_type,
        focus_dimension="综合观点",
        target_scope="opponent",
        answer_shape="general-list",
        ranking_mode="balanced",
        answer_title="对方最可能提出的观点",
        answer_summary="保留完整候选观点，但会优先围绕用户问题重排和筛选。",
        retrieval_hints=["对方观点", "抗辩路径", "攻击点", "举证责任"],
    )


def _build_opponent_queries(profile: PredictionCaseProfile, intent: PredictionIntent) -> list[str]:
    queries: list[str] = []
    primary_focus = profile.dispute_focuses[0] if profile.dispute_focuses else "程序事项"
    relationship = profile.legal_relationship.strip()

    if profile.user_goal:
        queries.append(profile.user_goal)

    focus_hint = FOCUS_QUERY_HINTS.get(primary_focus, "对方抗辩 事实不清 举证责任")
    queries.append(f"{relationship} {primary_focus} {focus_hint}".strip())

    for hint in intent.retrieval_hints[:3]:
        claim_text = " ".join(profile.claim_targets[:2])
        conflict_text = " ".join(profile.core_conflicts[:2])
        queries.append(f"{relationship} {claim_text} {hint} {conflict_text}".strip())

    if profile.opponent_favorable_points:
        queries.append(f"{primary_focus} 对方表述 {_compact(profile.opponent_favorable_points[0], limit=80)}")
    elif profile.known_facts:
        queries.append(f"{primary_focus} 对方抗辩 {_compact(profile.known_facts[0], limit=80)}")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in queries:
        cleaned = re.sub(r"\s+", " ", item).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped[:5]


def _flatten_result_citations(results: list[Any]) -> tuple[list[ChatCitation], list[str]]:
    citations: list[ChatCitation] = []
    summaries: list[str] = []
    seen: set[tuple[str, int, int, str]] = set()

    for doc in results:
        if (doc.source_path or "").startswith("template://"):
            continue
        if (doc.source_path or "").startswith("upload://"):
            continue
        for para in doc.paragraphs[:2]:
            key = (
                para.doc_id,
                para.citation.line_start,
                para.citation.line_end,
                para.citation.version_id,
            )
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                ChatCitation(
                    doc_id=para.doc_id,
                    file_name=para.citation.file_name,
                    line_start=para.citation.line_start,
                    line_end=para.citation.line_end,
                    version_id=para.citation.version_id,
                    snippet=(para.snippet or "").strip(),
                    similarity_score=float(para.similarity_score),
                )
            )
            summaries.append(_compact(para.snippet or para.match_explanation or "", limit=160))

    citations.sort(key=lambda item: item.similarity_score, reverse=True)
    return citations[:8], summaries[:8]


async def retrieve_opponent_support(
    db: Session,
    *,
    profile: PredictionCaseProfile,
    intent: PredictionIntent,
) -> RetrievalBundle:
    queries = _build_opponent_queries(profile, intent)
    all_citations: list[ChatCitation] = []
    all_summaries: list[str] = []

    for query in queries:
        try:
            response = await execute_search(
                SearchRequest(
                    query=query,
                    top_k_documents=6,
                    top_k_paragraphs=4,
                    dispute_focus=profile.dispute_focuses[0] if profile.dispute_focuses else None,
                ),
                db,
            )
            results = validate_and_enrich_results(db, response.results)
            citations, summaries = _flatten_result_citations(results)
            all_citations.extend(citations)
            all_summaries.extend(summaries)
        except Exception:
            logger.exception("Opponent-side retrieval failed for query: %s", query)

    deduped: list[ChatCitation] = []
    seen: set[tuple[str, int, int, str]] = set()
    for citation in sorted(all_citations, key=lambda item: item.similarity_score, reverse=True):
        key = (citation.doc_id, citation.line_start, citation.line_end, citation.version_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return RetrievalBundle(citations=deduped[:8], summaries=all_summaries[:8], search_queries=queries)


def _make_argument(
    *,
    title: str,
    basis: str,
    counter: str,
    opponent_statement: str,
    citations: list[ChatCitation],
    label: str,
    category: str,
    sort_reason: str,
    priority: str,
) -> PredictedArgument:
    return PredictedArgument(
        title=title,
        basis=basis,
        counter=counter,
        opponent_statement=opponent_statement,
        priority=priority,
        citations=citations,
        inference_only=not bool(citations),
        label=label,
        category=category,
        sort_reason=sort_reason,
    )


def _fallback_candidate_arguments(
    profile: PredictionCaseProfile,
    retrieval: RetrievalBundle,
) -> list[PredictedArgument]:
    citations = retrieval.citations
    top_fact = profile.known_facts[0] if profile.known_facts else "当前事实链条仍需继续补强"
    top_opponent = (
        profile.opponent_favorable_points[0]
        if profile.opponent_favorable_points
        else "目前缺少明确对方口径，只能按常见抗辩路径保守推断"
    )
    top_gap = profile.missing_information[0] if profile.missing_information else "当前未识别到明显信息缺口"
    top_focus = profile.dispute_focuses[0] if profile.dispute_focuses else "程序事项"
    relationship = profile.legal_relationship or "当前法律关系"
    claim_text = "、".join(profile.claim_targets[:2]) or "案涉请求"
    core_conflict = profile.core_conflicts[0] if profile.core_conflicts else top_focus

    return [
        _make_argument(
            title="程序与主体资格层面的先行阻断",
            basis=f"在“{relationship}”下，对方可能先从程序或主体资格入手，尝试把争议导向“是否有权主张、是否适格、是否存在程序瑕疵”。当前争议焦点已触及：{top_focus}。",
            counter="先核查诉讼主体、收费/主张权源、通知送达、时效与管辖材料，避免被对方先行卡住程序入口。",
            opponent_statement="被告可能会主张：原告并非案涉权利义务关系中的适格主体，且其就收费权源、通知送达或程序完备性并未提交充分材料，在主体资格和程序基础均未厘清前，其相关请求不应直接获得支持。",
            citations=citations[:2],
            label="角度 1",
            category="procedure",
            sort_reason="程序抗辩一旦成立，最容易先截断我方主张。",
            priority="主打",
        ),
        _make_argument(
            title="围绕事实成立与履行过程发起实体抗辩",
            basis=f"对方大概率会围绕“{claim_text}”的基础事实是否真实、是否完整履行、责任是否实际发生来组织实体抗辩。当前可抽取的关键事实包括：{top_fact}。",
            counter="把合同约定、履行节点、费用计算和通知催告串成闭合事实链，避免对方把争议拉回事实不清。",
            opponent_statement="被告可能会主张：原告对案涉事实的陈述并不完整，关于合同履行、费用形成、占有使用或违约触发条件等关键环节，现有材料尚不足以证明被告应按原告诉请承担相应责任。",
            citations=citations[2:4],
            label="角度 2",
            category="merits",
            sort_reason="实体抗辩覆盖面最大，也是多数案件的主战场。",
            priority="主打",
        ),
        _make_argument(
            title="抓我方证据缺口和举证责任压力",
            basis=f"对方还可能集中攻击我方证据的真实性、关联性或完整性，尤其会围绕“{core_conflict}”放大如下缺口：{top_gap}。若已有对方语料，其现有口径也可能是：{top_opponent}。",
            counter="逐项排查金额口径、占用/履行期间、凭证形成过程和书面确认记录，优先补最容易被攻击的证据空档。",
            opponent_statement="被告可能会主张：原告提交的证据在形成过程、证明对象和相互印证关系上均存在不足，尚不能形成完整证据链，因此其主张至多属于单方陈述，不能当然作为认定责任和金额的依据。",
            citations=citations[4:6],
            label="角度 3",
            category="evidence",
            sort_reason="证据攻击最容易把对方的否认转化为我方举证压力。",
            priority="次打",
        ),
        _make_argument(
            title="就请求范围和损失计算压缩责任",
            basis="即便对方不完全否认基础事实，也常会退而求其次，对费用期间、损失口径、责任比例和市场标准提出缩减式抗辩。",
            counter="提前准备费用期间、计费标准、合同依据和市场参照，避免请求范围过宽导致被整体压缩。",
            opponent_statement="被告可能会主张：即便法院认定其需承担一定责任，原告诉请的期间、金额口径和损失范围仍明显偏宽，缺乏充分合同依据或市场依据，应当依法予以核减而非全额支持。",
            citations=citations[6:8],
            label="角度 4",
            category="damages",
            sort_reason="这是对方在无法全面否认责任时最常见的收缩打法。",
            priority="补充",
        ),
    ]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    fenced = stripped
    if fenced.startswith("```"):
        fenced = re.sub(r"^```(?:json)?\s*", "", fenced)
        fenced = re.sub(r"\s*```$", "", fenced)
    try:
        parsed = json.loads(fenced)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    start = fenced.find("{")
    end = fenced.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(fenced[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


async def _generate_arguments_with_llm(
    profile: PredictionCaseProfile,
    intent: PredictionIntent,
    retrieval: RetrievalBundle,
) -> list[PredictedArgument] | None:
    if not DEEPSEEK_API_KEY:
        return None

    evidence_lines = []
    for index, citation in enumerate(retrieval.citations[:8], start=1):
        evidence_lines.append(
            {
                "index": index,
                "file_name": citation.file_name,
                "line_range": f"{citation.line_start}-{citation.line_end}",
                "snippet": citation.snippet,
            }
        )

    payload = {
        "case_name": profile.case_name,
        "user_goal": profile.user_goal,
        "intent": {
            "question_type": intent.question_type,
            "focus_dimension": intent.focus_dimension,
            "answer_shape": intent.answer_shape,
            "answer_title": intent.answer_title,
            "answer_summary": intent.answer_summary,
        },
        "party_roles": profile.party_roles,
        "legal_relationship": profile.legal_relationship,
        "dispute_focuses": profile.dispute_focuses,
        "known_facts": profile.known_facts,
        "timeline": profile.timeline,
        "claim_targets": profile.claim_targets,
        "core_conflicts": profile.core_conflicts,
        "missing_information": profile.missing_information,
        "opponent_favorable_points": profile.opponent_favorable_points,
        "retrieval_queries": retrieval.search_queries,
        "retrieval_evidence": evidence_lines,
    }
    system_prompt = (
        "你是法律攻防分析助手。你的任务不是泛泛预测，而是严格围绕用户问题输出结构化结果。"
        "先理解用户在问什么，再从对方视角给出最贴题的观点。"
        "只输出 JSON，格式为："
        "{\"arguments\":[{\"title\":\"\",\"basis\":\"\",\"counter\":\"\",\"opponent_statement\":\"\",\"priority\":\"\",\"label\":\"\",\"category\":\"\",\"sort_reason\":\"\",\"evidence_indexes\":[1,2]}]}"
        "要求：arguments 最多 4 个；label 要贴合问题类型，例如“角度 1”“Top 1”“攻击点 1”；"
        "basis 必须直接回答用户问题；opponent_statement 必须用对方口吻写成一段像答辩意见的表述；"
        "priority 只能是“主打”“次打”“补充”；sort_reason 解释为什么这条应该排在当前位置；"
        "没有证据支持时 evidence_indexes 返回空数组。"
    )
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1200,
                },
            )
        if response.status_code != 200:
            logger.warning("Prediction LLM failed: status=%s body=%s", response.status_code, response.text[:300])
            return None
        content = (((response.json().get("choices") or [{}])[0]).get("message") or {}).get("content", "")
        parsed = _extract_json_object(content)
        if not parsed or not isinstance(parsed.get("arguments"), list):
            return None
        arguments: list[PredictedArgument] = []
        for item in parsed["arguments"][:4]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            basis = str(item.get("basis") or "").strip()
            counter = str(item.get("counter") or "").strip()
            opponent_statement = str(item.get("opponent_statement") or item.get("opponentStatement") or "").strip()
            label = str(item.get("label") or "").strip() or "观点"
            category = str(item.get("category") or "").strip() or "general"
            sort_reason = str(item.get("sort_reason") or "").strip() or "与当前问题更贴近。"
            priority = str(item.get("priority") or "").strip() or "补充"
            indexes = item.get("evidence_indexes") or []
            local_citations: list[ChatCitation] = []
            for index in indexes:
                if isinstance(index, int) and 1 <= index <= len(retrieval.citations):
                    local_citations.append(retrieval.citations[index - 1])
            if not title or not basis or not counter:
                continue
            arguments.append(
                _make_argument(
                    title=title,
                    basis=basis,
                    counter=counter,
                    opponent_statement=opponent_statement,
                    citations=local_citations,
                    label=label,
                    category=category,
                    sort_reason=sort_reason,
                    priority=priority,
                )
            )
        return arguments or None
    except Exception:
        logger.exception("Prediction LLM generation failed")
        return None


async def generate_candidate_arguments(
    profile: PredictionCaseProfile,
    intent: PredictionIntent,
    retrieval: RetrievalBundle,
) -> list[PredictedArgument]:
    generated = await _generate_arguments_with_llm(profile, intent, retrieval)
    if generated:
        return generated
    return _fallback_candidate_arguments(profile, retrieval)


def _score_argument_for_intent(argument: PredictedArgument, intent: PredictionIntent) -> int:
    score = 0
    title = f"{argument.title} {argument.basis} {argument.category}".lower()
    if intent.question_type == "rebuttal-angle":
        if argument.category in {"procedure", "merits", "evidence", "damages"}:
            score += 4
        if "角度" in argument.label:
            score += 2
    elif intent.question_type == "evidence-attack":
        if argument.category == "evidence":
            score += 6
        if any(token in title for token in ("证据", "举证", "真实性", "关联性")):
            score += 3
    elif intent.question_type == "procedure-attack":
        if argument.category == "procedure":
            score += 6
        if any(token in title for token in ("程序", "时效", "管辖", "送达", "主体")):
            score += 3
    elif intent.question_type == "strongest-point":
        if not argument.inference_only:
            score += 3
        if argument.category in {"procedure", "merits"}:
            score += 2
    elif intent.question_type == "sequence-strategy":
        if argument.category == "procedure":
            score += 3
        if any(token in title for token in ("先", "后", "顺序", "阶段")):
            score += 2
    else:
        if not argument.inference_only:
            score += 2
    score += max(0, 3 - min(len(argument.citations), 3))
    return score


def _label_for_rank(intent: PredictionIntent, rank: int, argument: PredictedArgument) -> str:
    if intent.question_type == "rebuttal-angle":
        return f"角度 {rank}"
    if intent.question_type == "evidence-attack":
        return f"攻击点 {rank}"
    if intent.question_type == "procedure-attack":
        return f"程序路径 {rank}"
    if intent.question_type == "strongest-point":
        return f"Top {rank}"
    if intent.question_type == "sequence-strategy":
        return "先手" if rank == 1 else f"后手 {rank - 1}"
    return argument.label or f"观点 {rank}"


def _priority_for_rank(intent: PredictionIntent, rank: int) -> str:
    if intent.question_type in {"strongest-point", "sequence-strategy"}:
        return "主打" if rank == 1 else "次打" if rank == 2 else "补充"
    if intent.question_type in {"rebuttal-angle", "procedure-attack", "evidence-attack"}:
        return "主打" if rank <= 2 else "次打" if rank == 3 else "补充"
    return "主打" if rank == 1 else "次打" if rank <= 3 else "补充"


def _fallback_opponent_statement(argument: PredictedArgument) -> str:
    if argument.opponent_statement:
        return argument.opponent_statement
    return (
        f"对方可能会主张：{argument.title}。"
        f"其通常会围绕“{argument.basis}”展开，并据此要求法院对我方请求不予支持或予以限缩。"
    )


def shape_arguments_for_intent(
    intent: PredictionIntent,
    candidate_arguments: list[PredictedArgument],
) -> list[PredictedArgument]:
    ranked = sorted(
        candidate_arguments,
        key=lambda argument: _score_argument_for_intent(argument, intent),
        reverse=True,
    )
    limit = 3 if intent.question_type in {"strongest-point", "sequence-strategy"} else 4
    shaped: list[PredictedArgument] = []
    for index, argument in enumerate(ranked[:limit], start=1):
        data = argument.model_dump()
        data["label"] = _label_for_rank(intent, index, argument)
        data["priority"] = _priority_for_rank(intent, index)
        data["opponent_statement"] = _fallback_opponent_statement(argument)
        if intent.question_type == "strongest-point" and argument.sort_reason:
            data["basis"] = f"{argument.basis}\n排序理由：{argument.sort_reason}"
        elif intent.question_type == "sequence-strategy" and argument.sort_reason:
            data["basis"] = f"{argument.basis}\n顺序原因：{argument.sort_reason}"
        shaped.append(PredictedArgument(**data))
    return shaped


def _build_case_summary(profile: PredictionCaseProfile, intent: PredictionIntent) -> str:
    focus_text = "、".join(profile.dispute_focuses[:3]) or "待补充"
    relationship = profile.legal_relationship or "待进一步识别"
    claim_text = "、".join(profile.claim_targets[:3]) or "待进一步识别"
    return (
        f"本次问题将按“{intent.focus_dimension}”来组织结果。"
        f"当前识别到的法律关系为：{relationship}；主要请求目标为：{claim_text}；主要争议焦点为：{focus_text}。"
        f"已提取关键事实 {len(profile.known_facts)} 条，"
        f"信息缺口 {len(profile.missing_information)} 项。"
    )


async def build_prediction_report(
    db: Session,
    *,
    session_id: str,
    template_id: str,
    query: str,
) -> OpponentPredictionReport:
    validate_prediction_template_ready(db, template_id)
    template = _load_prediction_template_or_404(db, template_id)
    intent = infer_prediction_intent(query)
    profile = await build_case_profile(db, template_id=template_id, query=query)
    retrieval = await retrieve_opponent_support(db, profile=profile, intent=intent)
    candidate_arguments = await generate_candidate_arguments(profile, intent, retrieval)
    predicted_arguments = shape_arguments_for_intent(intent, candidate_arguments)

    task_id = f"pred_{uuid.uuid4().hex[:12]}"
    report_id = str(uuid.uuid4())
    report = OpponentPredictionReport(
        report_id=report_id,
        task_id=task_id,
        session_id=session_id,
        template_id=template_id,
        case_name=template.case_name,
        query=query,
        case_summary=_build_case_summary(profile, intent),
        predicted_arguments=predicted_arguments,
        counter_strategies=[item.counter for item in predicted_arguments],
        citations=retrieval.citations[:6],
        evidence_count=sum(1 for item in predicted_arguments if not item.inference_only),
        inference_count=sum(1 for item in predicted_arguments if item.inference_only),
        uncertainties=profile.missing_information or ["当前未识别到明显信息缺口。"],
        generated_at=datetime.utcnow(),
        question_type=intent.question_type,
        focus_dimension=intent.focus_dimension,
        answer_shape=intent.answer_shape,
        answer_title=intent.answer_title,
        answer_summary=intent.answer_summary,
        retrieval_queries=retrieval.search_queries,
    )

    db.add(
        PredictionReportSnapshotTable(
            report_id=report_id,
            task_id=task_id,
            session_id=session_id,
            template_id=template_id,
            user_query=query,
            report_json=json.dumps(report.model_dump(mode="json"), ensure_ascii=False),
        )
    )
    db.commit()
    return report
