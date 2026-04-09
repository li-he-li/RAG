"""
Persistence helpers for opponent-prediction templates and assets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.db_tables import (
    PredictionReportSnapshotTable,
    PredictionTemplateAssetParagraphTable,
    PredictionTemplateAssetTable,
    PredictionTemplateTable,
)
from app.models.schemas import (
    PredictionAssetKind,
    PredictionTemplateAssetItem,
    PredictionTemplateDetail,
    PredictionTemplateItem,
)
from app.core.uploads import read_upload_bytes
from app.services.file_extract import extract_upload_text
from app.services.parser import parse_document


MAX_CONTENT_PREVIEW_CHARS = 4000


def _to_asset_item(asset: PredictionTemplateAssetTable) -> PredictionTemplateAssetItem:
    return PredictionTemplateAssetItem(
        asset_id=asset.asset_id,
        template_id=asset.template_id,
        asset_kind=PredictionAssetKind(asset.asset_kind),
        file_name=asset.file_name,
        mime_type=asset.mime_type or "",
        size_bytes=int(asset.size_bytes or 0),
        content_chars=len(asset.content_text or ""),
        total_lines=int(asset.total_lines or 0),
        version_id=asset.version_id,
        content_preview=asset.content_preview or None,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _count_assets_by_kind(assets: Iterable[PredictionTemplateAssetTable], kind: PredictionAssetKind) -> int:
    return sum(1 for asset in assets if asset.asset_kind == kind.value)


def _to_template_detail(
    template: PredictionTemplateTable,
    assets: list[PredictionTemplateAssetTable],
) -> PredictionTemplateDetail:
    return PredictionTemplateDetail(
        template_id=template.template_id,
        case_name=template.case_name,
        case_material_count=_count_assets_by_kind(assets, PredictionAssetKind.CASE_MATERIAL),
        opponent_corpus_count=_count_assets_by_kind(assets, PredictionAssetKind.OPPONENT_CORPUS),
        created_at=template.created_at,
        updated_at=template.updated_at,
        created_by_session_id=template.created_by_session_id,
        assets=[_to_asset_item(asset) for asset in assets],
    )


def list_prediction_templates(db: Session) -> list[PredictionTemplateItem]:
    templates = (
        db.query(PredictionTemplateTable)
        .order_by(PredictionTemplateTable.updated_at.desc(), PredictionTemplateTable.created_at.desc())
        .all()
    )
    if not templates:
        return []

    template_ids = [template.template_id for template in templates]
    assets = (
        db.query(PredictionTemplateAssetTable)
        .filter(PredictionTemplateAssetTable.template_id.in_(template_ids))
        .all()
    )
    asset_map: dict[str, list[PredictionTemplateAssetTable]] = {}
    for asset in assets:
        asset_map.setdefault(asset.template_id, []).append(asset)

    items: list[PredictionTemplateItem] = []
    for template in templates:
        template_assets = asset_map.get(template.template_id, [])
        items.append(
            PredictionTemplateItem(
                template_id=template.template_id,
                case_name=template.case_name,
                case_material_count=_count_assets_by_kind(template_assets, PredictionAssetKind.CASE_MATERIAL),
                opponent_corpus_count=_count_assets_by_kind(template_assets, PredictionAssetKind.OPPONENT_CORPUS),
                created_at=template.created_at,
                updated_at=template.updated_at,
            )
        )
    return items


def get_prediction_template_detail(db: Session, template_id: str) -> PredictionTemplateDetail:
    template = (
        db.query(PredictionTemplateTable)
        .filter(PredictionTemplateTable.template_id == template_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail=f"Prediction template {template_id} not found")

    assets = (
        db.query(PredictionTemplateAssetTable)
        .filter(PredictionTemplateAssetTable.template_id == template_id)
        .order_by(PredictionTemplateAssetTable.created_at.asc())
        .all()
    )
    return _to_template_detail(template, assets)


def create_prediction_template(
    db: Session,
    *,
    case_name: str,
    created_by_session_id: str | None = None,
) -> PredictionTemplateTable:
    cleaned_name = case_name.strip()
    if not cleaned_name:
        raise HTTPException(status_code=400, detail="case_name is required")

    template = PredictionTemplateTable(
        case_name=cleaned_name,
        created_by_session_id=(created_by_session_id or "").strip() or None,
    )
    db.add(template)
    db.flush()
    return template


async def add_prediction_template_assets(
    db: Session,
    *,
    template_id: str,
    asset_kind: PredictionAssetKind,
    files: list[UploadFile],
    commit: bool = True,
) -> list[PredictionTemplateAssetItem]:
    template = (
        db.query(PredictionTemplateTable)
        .filter(PredictionTemplateTable.template_id == template_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail=f"Prediction template {template_id} not found")

    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    items: list[PredictionTemplateAssetItem] = []
    for file in files:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        raw = await read_upload_bytes(file)
        content = extract_upload_text(file.filename, raw)
        parsed = parse_document(
            content=content,
            file_name=file.filename,
            source_path=f"prediction://{template_id}/{asset_kind.value}/{file.filename}",
        )
        asset = PredictionTemplateAssetTable(
            asset_id=parsed.doc_id,
            template_id=template_id,
            asset_kind=asset_kind.value,
            file_name=file.filename,
            mime_type=file.content_type or "",
            size_bytes=len(raw),
            version_id=parsed.version_id,
            total_lines=parsed.total_lines,
            content_text="\n".join(parsed.normalized_lines),
            content_preview=("\n".join(parsed.normalized_lines))[:MAX_CONTENT_PREVIEW_CHARS],
        )
        db.add(asset)

        for paragraph in parsed.paragraphs:
            db.add(
                PredictionTemplateAssetParagraphTable(
                    para_id=paragraph.para_id,
                    asset_id=asset.asset_id,
                    template_id=template_id,
                    line_start=paragraph.line_start,
                    line_end=paragraph.line_end,
                    content=paragraph.content,
                    dispute_tags=",".join(paragraph.dispute_tags),
                )
            )

        db.flush()
        items.append(_to_asset_item(asset))

    template.updated_at = datetime.utcnow()
    if commit:
        db.commit()
    return items


def validate_prediction_template_ready(db: Session, template_id: str) -> None:
    template = (
        db.query(PredictionTemplateTable)
        .filter(PredictionTemplateTable.template_id == template_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail=f"Prediction template {template_id} not found")

    count = (
        db.query(PredictionTemplateAssetTable)
        .filter(PredictionTemplateAssetTable.template_id == template_id)
        .filter(PredictionTemplateAssetTable.asset_kind == PredictionAssetKind.CASE_MATERIAL.value)
        .count()
    )
    if count <= 0:
        raise HTTPException(status_code=400, detail="At least one case_material is required")


def delete_prediction_asset(db: Session, asset_id: str) -> PredictionTemplateAssetItem:
    asset = (
        db.query(PredictionTemplateAssetTable)
        .filter(PredictionTemplateAssetTable.asset_id == asset_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail=f"Prediction asset {asset_id} not found")

    deleted_item = _to_asset_item(asset)
    db.query(PredictionTemplateAssetParagraphTable).filter(
        PredictionTemplateAssetParagraphTable.asset_id == asset_id
    ).delete()
    db.delete(asset)
    db.commit()
    return deleted_item


def delete_prediction_template(db: Session, template_id: str) -> None:
    template = (
        db.query(PredictionTemplateTable)
        .filter(PredictionTemplateTable.template_id == template_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail=f"Prediction template {template_id} not found")

    asset_ids = [
        row.asset_id
        for row in db.query(PredictionTemplateAssetTable.asset_id)
        .filter(PredictionTemplateAssetTable.template_id == template_id)
        .all()
    ]
    if asset_ids:
        db.query(PredictionTemplateAssetParagraphTable).filter(
            PredictionTemplateAssetParagraphTable.asset_id.in_(asset_ids)
        ).delete(synchronize_session=False)
    db.query(PredictionTemplateAssetTable).filter(
        PredictionTemplateAssetTable.template_id == template_id
    ).delete(synchronize_session=False)
    db.query(PredictionReportSnapshotTable).filter(
        PredictionReportSnapshotTable.template_id == template_id
    ).delete(synchronize_session=False)
    db.delete(template)
    db.commit()
