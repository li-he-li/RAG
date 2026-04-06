"""
SQLAlchemy ORM table definitions for PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentTable(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    normalized_content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ParagraphTable(Base):
    __tablename__ = "paragraphs"

    para_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    doc_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    dispute_tags: Mapped[str] = mapped_column(Text, default="")  # comma-separated
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PredictionTemplateTable(Base):
    __tablename__ = "prediction_templates"

    template_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    case_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_by_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PredictionTemplateAssetTable(Base):
    __tablename__ = "prediction_template_assets"

    asset_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    content_text: Mapped[str] = mapped_column(Text, default="")
    content_preview: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PredictionTemplateAssetParagraphTable(Base):
    __tablename__ = "prediction_template_asset_paragraphs"

    para_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    dispute_tags: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PredictionReportSnapshotTable(Base):
    __tablename__ = "prediction_report_snapshots"

    report_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_query: Mapped[str] = mapped_column(Text, default="")
    report_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
