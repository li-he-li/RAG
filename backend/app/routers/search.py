"""
API router for similarity search endpoints.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_bootstrap_status, get_bootstrap_missing_components
from app.core.database import get_session
from app.models.db_tables import DocumentTable, ParagraphTable
from app.models.schemas import (
    BootstrapStatus,
    ChatRequest,
    ChatResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentListItem,
    ErrorResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.indexer import ingest_document, delete_document
from app.services.chat import execute_grounded_chat
from app.services.retrieval import execute_search
from app.services.traceability import validate_and_enrich_results, TraceabilityValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["legal-search"])


def _ensure_retrieval_ready() -> None:
    """Preflight gate: block retrieval endpoints until bootstrap completes."""
    status = get_bootstrap_status()
    if status.get("all_ready", False):
        return
    missing = get_bootstrap_missing_components()
    detail = "Retrieval service is unavailable until bootstrap completes."
    if missing:
        detail = f"{detail} Missing: {', '.join(missing)}"
    raise HTTPException(status_code=503, detail=detail)


def _extract_upload_text(file_name: str, raw: bytes) -> str:
    """Extract plain text from supported upload types."""
    ext = Path(file_name).suffix.lower()

    if ext in {".txt", ".md"}:
        return raw.decode("utf-8", errors="replace")

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"PDF 解析依赖未安装: {exc}",
            ) from exc

        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join((page.extract_text() or "").strip() for page in reader.pages)
        if not text.strip():
            raise HTTPException(status_code=422, detail="PDF 未提取到可用文本内容")
        return text

    if ext == ".docx":
        try:
            from docx import Document
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"DOCX 解析依赖未安装: {exc}",
            ) from exc

        doc = Document(io.BytesIO(raw))
        text = "\n".join((p.text or "").strip() for p in doc.paragraphs)
        if not text.strip():
            raise HTTPException(status_code=422, detail="DOCX 未提取到可用文本内容")
        return text

    if ext == ".doc":
        raise HTTPException(
            status_code=415,
            detail="暂不支持 .doc，请先另存为 .docx 后上传",
        )

    raise HTTPException(
        status_code=415,
        detail="不支持的文件类型，仅支持 .txt .md .pdf .docx",
    )


# ---------------------------------------------------------------------------
# 5.1 Similarity search endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/search",
    response_model=SearchResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Service not ready"},
        422: {"model": ErrorResponse, "description": "Citation metadata validation failed"},
    },
)
async def similarity_search(
    request: SearchRequest,
    db: Session = Depends(get_session),
):
    """
    Execute a dual-layer legal similarity search.

    Returns ranked document-level matches with nested paragraph-level evidence.
    Each paragraph evidence hit includes mandatory citation metadata
    (file_name, line_start, line_end, version_id) and a match explanation.
    """
    _ensure_retrieval_ready()
    try:
        response = await execute_search(request, db)
        # Validate and enrich results with snippet extraction and version checks
        response.results = validate_and_enrich_results(db, response.results)
        return response
    except TraceabilityValidationError as e:
        return JSONResponse(status_code=422, content=e.error.model_dump())
    except Exception as e:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Grounded DeepSeek chat endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Service not ready"},
        422: {"model": ErrorResponse, "description": "Citation metadata validation failed"},
    },
)
async def grounded_chat(
    request: ChatRequest,
    db: Session = Depends(get_session),
):
    """Chat with DeepSeek using only database-grounded legal evidence."""
    _ensure_retrieval_ready()
    try:
        return await execute_grounded_chat(request, db)
    except TraceabilityValidationError as e:
        return JSONResponse(status_code=422, content=e.error.model_dump())
    except Exception as e:
        logger.exception("Grounded chat failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Document ingestion endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/documents",
    response_model=DocumentIngestResponse,
)
async def ingest_document_endpoint(
    request: DocumentIngestRequest,
    db: Session = Depends(get_session),
):
    """Ingest a document into the search index.

    The document will be parsed, segmented into paragraphs, embedded,
    and indexed in both PostgreSQL and Qdrant.
    """
    try:
        result = ingest_document(
            db=db,
            content=request.content,
            file_name=request.file_name,
            source_path=request.source_path,
            version_id=request.version_id,
        )
        return result
    except Exception as e:
        logger.exception("Document ingestion failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/documents/upload",
    response_model=DocumentIngestResponse,
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    """Upload and ingest a document file.

    Supports .txt .md .pdf .docx files.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    raw = await file.read()
    content = _extract_upload_text(file.filename, raw)
    result = ingest_document(
        db=db,
        content=content,
        file_name=file.filename,
        source_path=f"upload://{file.filename}",
    )
    return result


@router.get(
    "/documents",
    response_model=list[DocumentListItem],
)
async def list_documents(
    limit: int = 100,
    db: Session = Depends(get_session),
):
    """List uploaded documents persisted in PostgreSQL."""
    limit = max(1, min(limit, 500))
    rows = (
        db.query(
            DocumentTable.doc_id,
            DocumentTable.file_name,
            DocumentTable.version_id,
            DocumentTable.total_lines,
            DocumentTable.created_at,
            DocumentTable.updated_at,
            func.count(ParagraphTable.para_id).label("paragraphs_indexed"),
        )
        .outerjoin(ParagraphTable, ParagraphTable.doc_id == DocumentTable.doc_id)
        .group_by(
            DocumentTable.doc_id,
            DocumentTable.file_name,
            DocumentTable.version_id,
            DocumentTable.total_lines,
            DocumentTable.created_at,
            DocumentTable.updated_at,
        )
        .order_by(DocumentTable.updated_at.desc(), DocumentTable.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        DocumentListItem(
            doc_id=row.doc_id,
            file_name=row.file_name,
            version_id=row.version_id,
            total_lines=row.total_lines,
            paragraphs_indexed=int(row.paragraphs_indexed or 0),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.delete("/documents/{doc_id}")
async def delete_document_endpoint(
    doc_id: str,
    db: Session = Depends(get_session),
):
    """Delete a document and all associated data."""
    success = delete_document(db, doc_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return {"status": "deleted", "doc_id": doc_id}


# ---------------------------------------------------------------------------
# Health and bootstrap status
# ---------------------------------------------------------------------------

@router.get("/health", response_model=BootstrapStatus)
async def health_check():
    """Check the readiness of all system components."""
    from app.core.config import (
        PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE,
        QDRANT_HOST, QDRANT_PORT,
    )

    status = BootstrapStatus()

    # Check PostgreSQL
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT,
            user=PG_USER, password=PG_PASSWORD,
            dbname=PG_DATABASE,
        )
        conn.close()
        status.postgresql_ready = True
    except Exception:
        status.postgresql_ready = False

    # Check Qdrant
    try:
        import requests
        resp = requests.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/healthz", timeout=3)
        status.qdrant_ready = resp.status_code == 200
    except Exception:
        status.qdrant_ready = False

    # Check embedding model (lightweight check - just try to get the model)
    try:
        from app.core.config import EMBEDDING_PROVIDER
        if EMBEDDING_PROVIDER == "google":
            from app.services.embedding import _get_google_client
            _get_google_client()
        else:
            from app.services.embedding import _get_local_model
            _get_local_model()
        status.embedding_model_ready = True
    except Exception:
        status.embedding_model_ready = False

    # Check reranker model
    try:
        from app.services.reranker import _get_reranker
        _get_reranker()
        status.reranker_model_ready = True
    except Exception:
        status.reranker_model_ready = False

    status.all_ready = all([
        status.postgresql_ready,
        status.qdrant_ready,
        status.embedding_model_ready,
        status.reranker_model_ready,
    ])

    if status.all_ready:
        status.message = "All components are ready."
    else:
        missing = []
        if not status.postgresql_ready:
            missing.append("PostgreSQL")
        if not status.qdrant_ready:
            missing.append("Qdrant")
        if not status.embedding_model_ready:
            missing.append("Embedding Model")
        if not status.reranker_model_ready:
            missing.append("Reranker Model")
        status.message = f"Not ready: {', '.join(missing)}"

    return status


@router.post("/bootstrap")
async def trigger_bootstrap():
    """Manually trigger the bootstrap process."""
    from app.core.config import run_bootstrap
    status = run_bootstrap()
    return status
