"""
Indexing service: builds document-level and paragraph-level embedding indices.
Handles ingestion of parsed documents into PostgreSQL + Qdrant.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.db_tables import DocumentTable, ParagraphTable
from app.models.schemas import DocumentIngestResponse
from app.services.embedding import encode_texts
from app.services.parser import ParsedDocument, parse_document
from app.services.vector_store import (
    init_collections,
    upsert_document_vector,
    upsert_paragraph_vectors,
    delete_document_vectors,
)

logger = logging.getLogger(__name__)


def ingest_document(
    db: Session,
    content: str,
    file_name: str,
    source_path: str,
    doc_id: Optional[str] = None,
    version_id: Optional[str] = None,
) -> DocumentIngestResponse:
    """Full ingestion pipeline: parse -> store in PG -> embed -> index in Qdrant.

    Args:
        db: SQLAlchemy session.
        content: Raw document text.
        file_name: File name.
        source_path: Source file path.
        doc_id: Optional doc_id override.
        version_id: Optional version_id override.

    Returns:
        DocumentIngestResponse with metadata about the ingested document.
    """
    # 1. Parse document
    parsed = parse_document(content, file_name, source_path, doc_id, version_id)

    # 2. Store in PostgreSQL
    # Check if document already exists (re-ingestion with version update)
    existing = db.query(DocumentTable).filter_by(doc_id=parsed.doc_id).first()
    if existing:
        # Delete old vectors
        delete_document_vectors(parsed.doc_id)
        # Delete old paragraphs
        db.query(ParagraphTable).filter_by(doc_id=parsed.doc_id).delete()
        # Update document record
        existing.file_name = parsed.file_name
        existing.source_path = parsed.source_path
        existing.version_id = parsed.version_id
        existing.total_lines = parsed.total_lines
        existing.normalized_content = "\n".join(parsed.normalized_lines)
    else:
        doc_record = DocumentTable(
            doc_id=parsed.doc_id,
            file_name=parsed.file_name,
            source_path=parsed.source_path,
            version_id=parsed.version_id,
            total_lines=parsed.total_lines,
            normalized_content="\n".join(parsed.normalized_lines),
        )
        db.add(doc_record)

    # 3. Generate document-level embedding
    doc_text = "\n".join(parsed.normalized_lines)
    doc_vectors = encode_texts([doc_text])
    doc_vector = doc_vectors[0]

    # 4. Generate paragraph-level embeddings
    para_texts = [p.content for p in parsed.paragraphs]
    para_vectors = []
    if para_texts:
        para_vectors = encode_texts(para_texts)

    # 5. Upsert document vector to Qdrant
    upsert_document_vector(
        doc_id=parsed.doc_id,
        vector=doc_vector,
        payload={
            "doc_id": parsed.doc_id,
            "file_name": parsed.file_name,
            "source_path": parsed.source_path,
            "version_id": parsed.version_id,
            "total_lines": parsed.total_lines,
        },
    )

    # 6. Upsert paragraph vectors to Qdrant
    if parsed.paragraphs:
        points = []
        for i, para in enumerate(parsed.paragraphs):
            # Store paragraph in PostgreSQL
            para_record = ParagraphTable(
                para_id=para.para_id,
                doc_id=parsed.doc_id,
                line_start=para.line_start,
                line_end=para.line_end,
                content=para.content,
                dispute_tags=",".join(para.dispute_tags),
            )
            db.add(para_record)

            points.append(
                {
                    "para_id": para.para_id,
                    "vector": para_vectors[i],
                    "payload": {
                        "para_id": para.para_id,
                        "doc_id": parsed.doc_id,
                        "line_start": para.line_start,
                        "line_end": para.line_end,
                        "dispute_tags": para.dispute_tags,
                        "file_name": parsed.file_name,
                        "version_id": parsed.version_id,
                    },
                }
            )

        upsert_paragraph_vectors(points)

    db.commit()

    return DocumentIngestResponse(
        doc_id=parsed.doc_id,
        version_id=parsed.version_id,
        total_lines=parsed.total_lines,
        paragraphs_indexed=len(parsed.paragraphs),
        status="ok",
    )


def delete_document(
    db: Session,
    doc_id: str,
) -> bool:
    """Delete a document and all its paragraphs from PG + Qdrant."""
    doc = db.query(DocumentTable).filter_by(doc_id=doc_id).first()
    if not doc:
        return False

    # Delete from Qdrant
    delete_document_vectors(doc_id)

    # Delete paragraphs from PG
    db.query(ParagraphTable).filter_by(doc_id=doc_id).delete()

    # Delete document from PG
    db.delete(doc)
    db.commit()
    return True
