"""
API router for opponent-prediction template management and start flow.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents.base import ValidatedOutput
from app.core.database import get_session
from app.core.http_errors import internal_error_detail
from app.models.schemas import (
    OpponentPredictionReport,
    OpponentPredictionStartRequest,
    PredictionAssetDeleteResponse,
    PredictionAssetKind,
    PredictionTemplateAssetItem,
    PredictionTemplateDeleteResponse,
    PredictionTemplateDetail,
    PredictionTemplateItem,
)
from app.services.prediction_templates import (
    add_prediction_template_assets,
    create_prediction_template,
    delete_prediction_asset,
    delete_prediction_template,
    get_prediction_template_detail,
    list_prediction_templates,
    validate_prediction_template_ready,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["opponent-prediction"])


@router.post(
    "/prediction/templates",
    response_model=PredictionTemplateDetail,
)
async def create_prediction_template_endpoint(
    case_name: str = Form(...),
    session_id: str | None = Form(default=None),
    case_materials: list[UploadFile] = File(...),
    opponent_corpus: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_session),
):
    """Create a prediction template with required case materials."""
    if not case_name.strip():
        raise HTTPException(status_code=400, detail="case_name is required")
    if not case_materials:
        raise HTTPException(status_code=400, detail="At least one case_material is required")

    try:
        template = create_prediction_template(
            db,
            case_name=case_name,
            created_by_session_id=session_id,
        )
        await add_prediction_template_assets(
            db,
            template_id=template.template_id,
            asset_kind=PredictionAssetKind.CASE_MATERIAL,
            files=case_materials,
            commit=False,
        )
        if opponent_corpus:
            await add_prediction_template_assets(
                db,
                template_id=template.template_id,
                asset_kind=PredictionAssetKind.OPPONENT_CORPUS,
                files=opponent_corpus,
                commit=False,
            )
        validate_prediction_template_ready(db, template.template_id)
        db.commit()
        return get_prediction_template_detail(db, template.template_id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create prediction template")
        raise HTTPException(status_code=500, detail=internal_error_detail(exc)) from exc


@router.get(
    "/prediction/templates",
    response_model=list[PredictionTemplateItem],
)
async def list_prediction_templates_endpoint(
    db: Session = Depends(get_session),
):
    return list_prediction_templates(db)


@router.get(
    "/prediction/templates/{template_id}",
    response_model=PredictionTemplateDetail,
)
async def get_prediction_template_endpoint(
    template_id: str,
    db: Session = Depends(get_session),
):
    return get_prediction_template_detail(db, template_id)


@router.delete(
    "/prediction/templates/{template_id}",
    response_model=PredictionTemplateDeleteResponse,
)
async def delete_prediction_template_endpoint(
    template_id: str,
    db: Session = Depends(get_session),
):
    delete_prediction_template(db, template_id)
    return PredictionTemplateDeleteResponse(template_id=template_id)


@router.post(
    "/prediction/templates/{template_id}/assets/upload",
    response_model=list[PredictionTemplateAssetItem],
)
async def upload_prediction_template_assets_endpoint(
    template_id: str,
    asset_kind: PredictionAssetKind = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_session),
):
    try:
        items = await add_prediction_template_assets(
            db,
            template_id=template_id,
            asset_kind=asset_kind,
            files=files,
        )
        if asset_kind == PredictionAssetKind.CASE_MATERIAL:
            validate_prediction_template_ready(db, template_id)
        return items
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to upload prediction template assets")
        raise HTTPException(status_code=500, detail=internal_error_detail(exc)) from exc


@router.delete(
    "/prediction/assets/{asset_id}",
    response_model=PredictionAssetDeleteResponse,
)
async def delete_prediction_asset_endpoint(
    asset_id: str,
    db: Session = Depends(get_session),
):
    deleted = delete_prediction_asset(db, asset_id)
    return PredictionAssetDeleteResponse(asset_id=deleted.asset_id)


@router.post(
    "/opponent-prediction/start",
    response_model=OpponentPredictionReport,
)
async def start_opponent_prediction(
    request: OpponentPredictionStartRequest,
    db: Session = Depends(get_session),
):
    session_id = request.session_id.strip()
    template_id = request.template_id.strip()
    query = request.query.strip()

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if not template_id:
        raise HTTPException(status_code=400, detail="template_id is required")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    try:
        from app.agents.compatibility import CompatibilityAdapter, EndpointContract
        from app.agents.orchestrator_integration import get_orchestrator

        contract = EndpointContract(
            name="opponent_prediction_start",
            response_mapper=lambda output: output if isinstance(output, dict) else {},
            public_stream_event_types=frozenset(),
        )
        adapter = CompatibilityAdapter(contract=contract)
        result = await get_orchestrator().dispatch(
            endpoint="/api/opponent-prediction/start",
            payload={
                "session_id": session_id,
                "template_id": template_id,
                "query": query,
                "db": db,
            },
        )
        if isinstance(result, ValidatedOutput) and result.metadata.get("error"):
            status_code = int(result.metadata.get("status_code") or 500)
            detail = result.metadata.get("detail") or internal_error_detail(
                RuntimeError(str(result.metadata.get("error")))
            )
            raise HTTPException(status_code=status_code, detail=detail)
        return adapter.adapt_response(result)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to start opponent prediction")
        raise HTTPException(status_code=500, detail=internal_error_detail(exc)) from exc
