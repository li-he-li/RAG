"""
Text extraction and paragraph segmentation pipeline.
Produces normalized text with stable line mapping per document version.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedDocument:
    """Result of parsing a document into normalized text + paragraphs."""
    doc_id: str
    file_name: str
    source_path: str
    version_id: str
    total_lines: int
    normalized_lines: list[str]
    paragraphs: list[ParsedParagraph]


@dataclass
class ParsedParagraph:
    """A single segmented paragraph with line mapping."""
    para_id: str
    doc_id: str
    line_start: int  # 1-based
    line_end: int    # 1-based, inclusive
    content: str
    dispute_tags: list[str] = field(default_factory=list)


# Dispute-focus keyword patterns for tagging
DISPUTE_PATTERNS = [
    (r"违约|违反合同|合同纠纷", "合同违约"),
    (r"赔偿|损害赔偿|经济赔偿|赔偿金", "损害赔偿"),
    (r"侵权|侵权行为|专利侵权|商标侵权", "侵权纠纷"),
    (r"劳动|劳动合同|工资|解雇|辞退", "劳动争议"),
    (r"离婚|抚养|赡养|婚姻", "婚姻家庭"),
    (r"继承|遗嘱|遗产", "继承纠纷"),
    (r"债务|欠款|借款|借贷|贷款", "债务纠纷"),
    (r"房屋|房产|租赁|租房|物业", "房产纠纷"),
    (r"知识产权|著作权|专利|商标", "知识产权"),
    (r"行政处罚|行政诉讼|复议", "行政纠纷"),
    (r"诈骗|盗窃|犯罪|刑事责任", "刑事"),
    (r"仲裁|调解|和解", "争议解决"),
    (r"管辖|受理|起诉|上诉|申诉", "程序事项"),
]


def _tag_dispute_focus(text: str) -> list[str]:
    """Apply rule-based dispute-focus tagging to a paragraph text."""
    tags = []
    for pattern, tag in DISPUTE_PATTERNS:
        if re.search(pattern, text):
            tags.append(tag)
    return tags


def normalize_text(raw_text: str) -> list[str]:
    """Normalize raw text into a list of non-empty lines with stable line numbers.

    Normalization rules:
    - Strip leading/trailing whitespace from each line
    - Remove completely blank lines but keep line count stable for referencing
    - Normalize Unicode whitespace
    """
    lines = raw_text.splitlines()
    normalized = []
    for line in lines:
        # Normalize whitespace but preserve content
        cleaned = line.strip()
        # Replace various unicode spaces with regular space
        cleaned = re.sub(r"[\u3000\u00a0]+", " ", cleaned)
        normalized.append(cleaned)
    return normalized


def segment_paragraphs(
    normalized_lines: list[str],
    doc_id: str,
    min_paragraph_lines: int = 1,
    max_paragraph_lines: int = 50,
) -> list[ParsedParagraph]:
    """Segment normalized lines into paragraphs based on structural cues.

    Paragraphs are split on:
    - Empty lines (blank lines in the normalized output)
    - Lines that look like headings (short, ending with punctuation like ：or ：)

    Each paragraph is tagged with dispute-focus keywords.
    """
    paragraphs = []
    current_start = None
    current_lines = []

    def flush():
        if not current_lines:
            return
        content = "\n".join(current_lines)
        tags = _tag_dispute_focus(content)
        paragraphs.append(
            ParsedParagraph(
                para_id=str(uuid.uuid4()),
                doc_id=doc_id,
                line_start=current_start,
                line_end=current_start + len(current_lines) - 1,
                content=content,
                dispute_tags=tags,
            )
        )

    for i, line in enumerate(normalized_lines, start=1):
        if not line:
            # Empty line = paragraph boundary
            flush()
            current_start = None
            current_lines = []
            continue

        if current_start is None:
            current_start = i

        current_lines.append(line)

        # If paragraph gets too long, force split
        if len(current_lines) >= max_paragraph_lines:
            flush()
            current_start = None
            current_lines = []

    # Flush remaining
    flush()

    # Merge paragraphs that are too short (single line) with previous if possible
    merged = []
    for p in paragraphs:
        if (
            merged
            and (p.line_end - p.line_start + 1) <= min_paragraph_lines
            and (merged[-1].line_end + 1) == p.line_start
        ):
            # Merge with previous
            prev = merged[-1]
            prev.content = prev.content + "\n" + p.content
            prev.line_end = p.line_end
            prev.dispute_tags = list(set(prev.dispute_tags + p.dispute_tags))
        else:
            merged.append(p)

    return merged


def parse_document(
    content: str,
    file_name: str,
    source_path: str,
    doc_id: Optional[str] = None,
    version_id: Optional[str] = None,
) -> ParsedDocument:
    """Full parsing pipeline: normalize text + segment paragraphs.

    Args:
        content: Raw document text.
        file_name: Name of the source file.
        source_path: Path to the source file.
        doc_id: Optional doc_id; auto-generated if not provided.
        version_id: Optional version_id; auto-generated if not provided.

    Returns:
        ParsedDocument with stable line mapping and paragraph segmentation.
    """
    doc_id = doc_id or str(uuid.uuid4())
    version_id = version_id or str(uuid.uuid4())[:8]

    normalized_lines = normalize_text(content)
    total_lines = len(normalized_lines)
    paragraphs = segment_paragraphs(normalized_lines, doc_id)

    return ParsedDocument(
        doc_id=doc_id,
        file_name=file_name,
        source_path=source_path,
        version_id=version_id,
        total_lines=total_lines,
        normalized_lines=normalized_lines,
        paragraphs=paragraphs,
    )
