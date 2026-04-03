"""
Traceability and evidence verification.
Ensures citation metadata completeness, source metadata completeness,
snippet resolution, and version consistency.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.db_tables import DocumentTable
from app.models.schemas import DocumentResult, ErrorResponse, ParagraphEvidence

logger = logging.getLogger(__name__)


class TraceabilityValidationError(Exception):
    """Raised when mandatory traceability metadata is invalid."""

    def __init__(self, error: ErrorResponse):
        self.error = error
        super().__init__(error.detail)


def validate_document_source_metadata(doc: DocumentResult) -> Optional[ErrorResponse]:
    """Validate required document-level source metadata."""
    missing = []
    if not doc.file_name:
        missing.append("file_name")
    if not doc.source_path:
        missing.append("source_path")
    if not doc.version_id:
        missing.append("version_id")

    if missing:
        return ErrorResponse(
            error="source_metadata_missing",
            detail=f"Source metadata missing for doc_id={doc.doc_id}: {', '.join(missing)}",
            citation_missing=False,
        )
    return None


def validate_citation_metadata(evidence: ParagraphEvidence) -> Optional[ErrorResponse]:
    """Validate mandatory citation fields for paragraph evidence."""
    issues = []
    if not evidence.citation.file_name:
        issues.append("file_name is missing")
    if evidence.citation.line_start <= 0:
        issues.append("line_start must be positive")
    if evidence.citation.line_end < evidence.citation.line_start:
        issues.append("line_end must be >= line_start")
    if not evidence.citation.version_id:
        issues.append("version_id is missing")

    if issues:
        return ErrorResponse(
            error="citation_incomplete",
            detail=(
                f"Citation metadata incomplete for para_id={evidence.para_id}: "
                f"{'; '.join(issues)}"
            ),
            citation_missing=True,
        )
    return None


def extract_evidence_snippet(
    db: Session,
    doc_id: str,
    line_start: int,
    line_end: int,
) -> str:
    """Extract a text snippet from stored normalized document content."""
    doc = db.query(DocumentTable).filter_by(doc_id=doc_id).first()
    if not doc or not doc.normalized_content:
        return ""

    lines = doc.normalized_content.splitlines()
    start_idx = max(0, line_start - 1)  # line_start is 1-based
    end_idx = min(len(lines), line_end)
    snippet_lines = lines[start_idx:end_idx]
    return "\n".join(snippet_lines)


def check_version_consistency(
    db: Session,
    doc_id: str,
    claimed_version_id: str,
) -> Optional[str]:
    """Check if claimed version matches current document version."""
    doc = db.query(DocumentTable).filter_by(doc_id=doc_id).first()
    if not doc:
        return f"Document {doc_id} not found"

    if doc.version_id != claimed_version_id:
        return (
            f"Version mismatch for doc_id={doc_id}: "
            f"referenced version={claimed_version_id}, "
            f"current version={doc.version_id}. "
            f"Line numbers may have shifted."
        )
    return None


def validate_and_enrich_results(
    db: Session,
    results: list[DocumentResult],
) -> list[DocumentResult]:
    """Validate and enrich retrieval results.

    Enforces:
    - document-level source metadata is present
    - paragraph-level citation metadata is present
    - citation line range can be resolved to snippet text
    """
    for doc in results:
        metadata_error = validate_document_source_metadata(doc)
        if metadata_error:
            logger.error(metadata_error.detail)
            raise TraceabilityValidationError(metadata_error)

        for para in doc.paragraphs:
            citation_error = validate_citation_metadata(para)
            if citation_error:
                logger.error(citation_error.detail)
                raise TraceabilityValidationError(citation_error)

            if not para.snippet:
                para.snippet = extract_evidence_snippet(
                    db, para.doc_id, para.line_start, para.line_end
                )

            if not para.snippet or not para.snippet.strip():
                unresolved = ErrorResponse(
                    error="citation_unresolved",
                    detail=(
                        "Unable to resolve citation reference for "
                        f"para_id={para.para_id}, doc_id={para.doc_id}, "
                        f"line_range={para.line_start}-{para.line_end}"
                    ),
                    citation_missing=False,
                )
                logger.error(unresolved.detail)
                raise TraceabilityValidationError(unresolved)

            warning = check_version_consistency(db, para.doc_id, para.citation.version_id)
            if warning:
                if warning.startswith("Document "):
                    unresolved = ErrorResponse(
                        error="citation_unresolved",
                        detail=warning,
                        citation_missing=False,
                    )
                    logger.error(unresolved.detail)
                    raise TraceabilityValidationError(unresolved)
                para.match_explanation = f"[VERSION WARNING] {warning}\n{para.match_explanation}"

    return results
