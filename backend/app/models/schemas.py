"""
Data models and schemas for legal similarity evidence search.
Defines the dual-layer response contract: document-level + paragraph-level.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Citation metadata (mandatory for every paragraph hit)
# ---------------------------------------------------------------------------

class CitationMetadata(BaseModel):
    """Mandatory citation fields that every paragraph-level hit must include."""
    file_name: str = Field(..., description="Source file name, e.g. 'case_001.txt'")
    line_start: int = Field(..., description="Start line number in the source file (1-based)")
    line_end: int = Field(..., description="End line number in the source file (inclusive)")
    version_id: str = Field(..., description="Document version identifier for traceability")


# ---------------------------------------------------------------------------
# Paragraph-level evidence
# ---------------------------------------------------------------------------

class ParagraphEvidence(BaseModel):
    """A single paragraph-level evidence hit within a document."""
    para_id: str = Field(..., description="Stable paragraph identifier")
    doc_id: str = Field(..., description="Parent document identifier")
    line_start: int = Field(..., description="Start line in the source file")
    line_end: int = Field(..., description="End line in the source file")
    dispute_tags: list[str] = Field(
        default_factory=list,
        description="Dispute-focus tags, e.g. ['合同违约', '损害赔偿']",
    )
    snippet: str = Field(..., description="Evidence text snippet from the paragraph")
    match_explanation: str = Field(
        default="",
        description="Human-readable explanation of why this paragraph matched",
    )
    similarity_score: float = Field(
        default=0.0,
        description="Similarity score for this paragraph hit [0, 1]",
    )
    citation: CitationMetadata = Field(
        ..., description="Mandatory citation metadata for verification"
    )


# ---------------------------------------------------------------------------
# Document-level result
# ---------------------------------------------------------------------------

class DocumentResult(BaseModel):
    """A document-level match with nested paragraph evidence."""
    doc_id: str = Field(..., description="Stable document identifier")
    file_name: str = Field(..., description="Source file name")
    source_path: str = Field(..., description="Full path to the source file")
    version_id: str = Field(..., description="Document version identifier")
    total_lines: int = Field(..., description="Total number of lines in the document")
    similarity_score: float = Field(
        default=0.0,
        description="Document-level similarity score [0, 1]",
    )
    paragraphs: list[ParagraphEvidence] = Field(
        default_factory=list,
        description="Paragraph-level evidence hits within this document",
    )


# ---------------------------------------------------------------------------
# Search request / response
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    """Request body for the similarity search endpoint."""
    query: str = Field(..., min_length=1, description="Search query text")
    top_k_documents: int = Field(default=5, ge=1, le=50, description="Max documents to return")
    top_k_paragraphs: int = Field(default=10, ge=1, le=100, description="Max paragraphs per document")
    dispute_focus: Optional[str] = Field(
        default=None,
        description="Optional dispute-focus filter to prioritize specific dispute types",
    )


class SearchResponse(BaseModel):
    """Dual-layer similarity search response."""
    query: str = Field(..., description="Original query text")
    total_documents: int = Field(..., description="Total number of document results")
    total_paragraphs: int = Field(..., description="Total number of paragraph evidence hits")
    results: list[DocumentResult] = Field(
        default_factory=list,
        description="Ranked document-level results with nested paragraph evidence",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# DeepSeek grounded chat request / response
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Request body for grounded DeepSeek chat over indexed legal evidence."""
    query: str = Field(..., min_length=1, description="User query text")
    top_k_documents: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum number of candidate documents used for grounding",
    )
    top_k_paragraphs: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Maximum number of paragraph evidence citations returned",
    )
    dispute_focus: Optional[str] = Field(
        default=None,
        description="Optional dispute-focus constraint for evidence retrieval",
    )


class ChatCitation(BaseModel):
    """A grounded citation sent to and returned from the chat pipeline."""
    doc_id: str = Field(..., description="Parent document identifier")
    file_name: str = Field(..., description="Source file name")
    line_start: int = Field(..., description="Citation start line")
    line_end: int = Field(..., description="Citation end line")
    version_id: str = Field(..., description="Document version identifier")
    snippet: str = Field(..., description="Evidence snippet extracted from indexed content")
    similarity_score: float = Field(
        default=0.0,
        description="Similarity score of the cited evidence paragraph",
    )


class ChatResponse(BaseModel):
    """DeepSeek chat response grounded by database evidence."""
    query: str = Field(..., description="Original user query")
    answer: str = Field(..., description="Grounded answer generated by DeepSeek")
    citations: list[ChatCitation] = Field(
        default_factory=list,
        description="Evidence citations used for the answer",
    )
    grounded: bool = Field(
        default=False,
        description="True when answer is grounded by retrieved citations",
    )
    used_documents: int = Field(
        default=0,
        description="Number of unique documents used in grounding context",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Ingest / index request
# ---------------------------------------------------------------------------

class DocumentIngestRequest(BaseModel):
    """Request to ingest a document into the index."""
    file_name: str = Field(..., description="File name of the document")
    source_path: str = Field(..., description="Path where the file is stored")
    content: str = Field(..., min_length=1, description="Full text content of the document")
    version_id: Optional[str] = Field(
        default=None,
        description="Optional version identifier; auto-generated if not provided",
    )


class DocumentIngestResponse(BaseModel):
    """Response after ingesting a document."""
    doc_id: str = Field(..., description="Assigned document identifier")
    version_id: str = Field(..., description="Version identifier")
    total_lines: int = Field(..., description="Total lines after normalization")
    paragraphs_indexed: int = Field(..., description="Number of paragraphs indexed")
    status: str = Field(default="ok")


class DocumentListItem(BaseModel):
    """A persisted uploaded document record for file management listing."""
    doc_id: str = Field(..., description="Document identifier")
    file_name: str = Field(..., description="Original uploaded file name")
    version_id: str = Field(..., description="Version identifier")
    total_lines: int = Field(..., description="Total normalized line count")
    paragraphs_indexed: int = Field(default=0, description="Indexed paragraph count")
    created_at: datetime = Field(..., description="Record creation time")
    updated_at: datetime = Field(..., description="Record update time")


# ---------------------------------------------------------------------------
# Session temp file models
# ---------------------------------------------------------------------------


class SessionTempFileKind(str, Enum):
    CHAT_ATTACHMENT = "chat_attachment"
    REVIEW_TARGET = "review_target"


class SessionTempFileItem(BaseModel):
    """A session-scoped temporary file stored outside persistent search assets."""

    file_id: str = Field(..., description="Temporary file identifier")
    session_id: str = Field(..., description="Owning chat session identifier")
    kind: SessionTempFileKind = Field(..., description="Temporary file usage kind")
    file_name: str = Field(..., description="Original uploaded file name")
    size_bytes: int = Field(..., ge=0, description="Uploaded file size in bytes")
    content_chars: int = Field(..., ge=0, description="Extracted text character count")
    created_at: datetime = Field(..., description="Temporary file creation time")
    updated_at: datetime = Field(..., description="Temporary file last update time")


class SessionTempClearResponse(BaseModel):
    """Response for clearing session-scoped temporary files."""

    session_id: str = Field(..., description="Chat session identifier")
    cleared: int = Field(..., ge=0, description="Number of temporary files removed")
    kind: Optional[SessionTempFileKind] = Field(
        default=None,
        description="Optional usage kind filter applied during cleanup",
    )


# ---------------------------------------------------------------------------
# Contract review template recommendation
# ---------------------------------------------------------------------------


class ReviewTemplateCandidate(BaseModel):
    """A template candidate ranked for the current review session."""

    id: str = Field(..., description="Template document identifier")
    name: str = Field(..., description="Template display name")
    score: float = Field(..., ge=0.0, le=1.0, description="Weighted overall recommendation score")
    confidence: str = Field(default="low", description="Relative confidence label for this candidate")
    semantic_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Semantic similarity score between review file and template",
    )
    title_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Title and contract-type keyword overlap score",
    )
    structure_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Clause and section structure overlap score",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable recommendation reasons",
    )


class ReviewTemplateRecommendationResponse(BaseModel):
    """Recommendation payload for review-target contracts in a session."""

    session_id: str = Field(..., description="Owning chat session identifier")
    review_file_count: int = Field(..., ge=0, description="Number of review-target files considered")
    recommended_template: Optional[ReviewTemplateCandidate] = Field(
        default=None,
        description="Highest-ranked recommended template",
    )
    candidate_templates: list[ReviewTemplateCandidate] = Field(
        default_factory=list,
        description="Selectable ranked template candidates",
    )


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Human-readable error detail")
    citation_missing: bool = Field(
        default=False,
        description="True if the error is due to missing citation metadata",
    )


# ---------------------------------------------------------------------------
# Bootstrap / health status
# ---------------------------------------------------------------------------

class BootstrapStatus(BaseModel):
    """Status of automatic dependency bootstrap."""
    postgresql_ready: bool = Field(default=False)
    qdrant_ready: bool = Field(default=False)
    embedding_model_ready: bool = Field(default=False)
    reranker_model_ready: bool = Field(default=False)
    all_ready: bool = Field(default=False)
    message: str = Field(default="")


# ---------------------------------------------------------------------------
# Internal DB model helpers
# ---------------------------------------------------------------------------

class DocumentRecord(BaseModel):
    """Internal record stored in PostgreSQL for each document."""
    doc_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_name: str
    source_path: str
    version_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    total_lines: int = 0
    normalized_content: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ParagraphRecord(BaseModel):
    """Internal record stored in PostgreSQL for each paragraph."""
    para_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str
    line_start: int
    line_end: int
    content: str = ""
    dispute_tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
