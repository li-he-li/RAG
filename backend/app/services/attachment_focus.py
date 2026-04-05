"""
Query-aware focus selection for session-scoped chat attachments.
Keeps processing entirely runtime-local and does not write to persistent storage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.embedding import encode_query, encode_texts
from app.services.parser import parse_document


MAX_FOCUS_CANDIDATES = 120
MAX_FOCUS_CHUNKS = 4
MAX_FOCUS_SUMMARY_CHARS = 1400
MAX_OVERVIEW_SUMMARY_CHARS = 900
MAX_FOCUS_QUERY_CHARS = 3200
QUERY_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}")


@dataclass(slots=True)
class AttachmentFocusChunk:
    line_start: int
    line_end: int
    text: str
    score: float

    @property
    def line_span(self) -> tuple[int, int]:
        return (self.line_start, self.line_end)

    def as_prompt_block(self) -> str:
        return f"第{self.line_start}-{self.line_end}行：\n{self.text}"


@dataclass(slots=True)
class AttachmentFocusResult:
    focused_query_text: str
    overview_summary: str
    focus_summary: str
    focus_chunks: list[AttachmentFocusChunk]


@dataclass(slots=True)
class _CandidateChunk:
    line_start: int
    line_end: int
    text: str


def _extract_query_terms(query: str) -> set[str]:
    return {match.group(0).lower() for match in QUERY_TERM_RE.finditer(query or "")}


def _build_candidate_chunks(content: str, file_name: str) -> list[_CandidateChunk]:
    parsed = parse_document(content=content, file_name=file_name, source_path=f"session://focus/{file_name}")
    paragraphs = [paragraph for paragraph in parsed.paragraphs if paragraph.content.strip()]
    if not paragraphs:
        normalized = content.strip()
        return [_CandidateChunk(line_start=1, line_end=max(1, len(normalized.splitlines())), text=normalized)] if normalized else []

    candidates: list[_CandidateChunk] = []
    for index, paragraph in enumerate(paragraphs):
        candidates.append(
            _CandidateChunk(
                line_start=paragraph.line_start,
                line_end=paragraph.line_end,
                text=paragraph.content.strip(),
            )
        )
        if index + 1 < len(paragraphs):
            next_paragraph = paragraphs[index + 1]
            pair_text = f"{paragraph.content.strip()}\n{next_paragraph.content.strip()}".strip()
            candidates.append(
                _CandidateChunk(
                    line_start=paragraph.line_start,
                    line_end=next_paragraph.line_end,
                    text=pair_text,
                )
            )

    unique: dict[tuple[int, int, str], _CandidateChunk] = {}
    for candidate in candidates:
        compact = re.sub(r"\s+", " ", candidate.text).strip()
        if len(compact) < 12:
            continue
        key = (candidate.line_start, candidate.line_end, compact)
        unique.setdefault(key, _CandidateChunk(candidate.line_start, candidate.line_end, compact))
        if len(unique) >= MAX_FOCUS_CANDIDATES:
            break
    return list(unique.values())


def _keyword_overlap_ratio(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    lower_text = text.lower()
    hits = sum(1 for term in query_terms if term in lower_text)
    return hits / len(query_terms)


def _overlap_ratio(left: tuple[int, int], right: tuple[int, int]) -> float:
    start = max(left[0], right[0])
    end = min(left[1], right[1])
    if end < start:
        return 0.0
    overlap = end - start + 1
    left_len = max(1, left[1] - left[0] + 1)
    right_len = max(1, right[1] - right[0] + 1)
    return overlap / min(left_len, right_len)


def _clip_text(text: str, limit: int) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _build_overview_summary(content: str, file_name: str) -> str:
    parsed = parse_document(content=content, file_name=file_name, source_path=f"session://overview/{file_name}")
    paragraphs = [paragraph.content.strip() for paragraph in parsed.paragraphs if paragraph.content.strip()]
    if not paragraphs:
        return _clip_text(content, MAX_OVERVIEW_SUMMARY_CHARS)

    indices = sorted({0, len(paragraphs) - 1, len(paragraphs) // 3, (len(paragraphs) * 2) // 3})
    parts: list[str] = []
    seen = set()
    for index in indices:
        if index < 0 or index >= len(paragraphs):
            continue
        text = _clip_text(paragraphs[index], 220)
        if not text or text in seen:
            continue
        seen.add(text)
        parts.append(text)
    return _clip_text("\n\n".join(parts), MAX_OVERVIEW_SUMMARY_CHARS)


def select_attachment_focus(*, content: str, file_name: str, query: str) -> AttachmentFocusResult | None:
    normalized_content = (content or "").strip()
    normalized_query = (query or "").strip()
    if not normalized_content or not normalized_query:
        return None

    candidates = _build_candidate_chunks(normalized_content, file_name)
    if not candidates:
        return None

    if len(candidates) == 1 and len(candidates[0].text) <= MAX_FOCUS_QUERY_CHARS:
        only = AttachmentFocusChunk(
            line_start=candidates[0].line_start,
            line_end=candidates[0].line_end,
            text=candidates[0].text,
            score=1.0,
        )
        clipped = _clip_text(candidates[0].text, MAX_FOCUS_QUERY_CHARS)
        return AttachmentFocusResult(
            focused_query_text=f"{clipped}\n\n{normalized_query}",
            overview_summary=_clip_text(candidates[0].text, MAX_OVERVIEW_SUMMARY_CHARS),
            focus_summary=_clip_text(candidates[0].text, MAX_FOCUS_SUMMARY_CHARS),
            focus_chunks=[only],
        )

    query_vector = encode_query(normalized_query)
    chunk_vectors = encode_texts([candidate.text for candidate in candidates])
    query_terms = _extract_query_terms(normalized_query)

    scored: list[AttachmentFocusChunk] = []
    for candidate, vector in zip(candidates, chunk_vectors, strict=False):
        semantic_score = sum(float(left) * float(right) for left, right in zip(query_vector, vector, strict=False))
        lexical_bonus = 0.08 * _keyword_overlap_ratio(query_terms, candidate.text)
        scored.append(
            AttachmentFocusChunk(
                line_start=candidate.line_start,
                line_end=candidate.line_end,
                text=candidate.text,
                score=semantic_score + lexical_bonus,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)

    selected: list[AttachmentFocusChunk] = []
    for chunk in scored:
        if any(_overlap_ratio(chunk.line_span, existing.line_span) >= 0.6 for existing in selected):
            continue
        selected.append(chunk)
        if len(selected) >= MAX_FOCUS_CHUNKS:
            break

    if not selected:
        return None

    selected.sort(key=lambda item: (item.line_start, item.line_end))
    focus_query_parts: list[str] = []
    summary_parts: list[str] = []
    for chunk in selected:
        focus_query_parts.append(chunk.text)
        summary_parts.append(chunk.as_prompt_block())

    overview_summary = _build_overview_summary(normalized_content, file_name)
    focused_query = _clip_text("\n\n".join(focus_query_parts), MAX_FOCUS_QUERY_CHARS)
    focus_summary = _clip_text("\n\n".join(summary_parts), MAX_FOCUS_SUMMARY_CHARS)
    return AttachmentFocusResult(
        focused_query_text=f"{overview_summary}\n\n{focused_query}\n\n{normalized_query}",
        overview_summary=overview_summary,
        focus_summary=focus_summary,
        focus_chunks=selected,
    )
