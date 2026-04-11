"""
Admin API for DSPy prompt optimization and variant management.

Endpoints:
- POST /api/admin/export-dspy-dataset — export trajectory data as DSPy Examples
- POST /api/admin/optimize-prompt — trigger DSPy optimization
- GET  /api/admin/prompt-variants/{name} — list variants for a prompt
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.trajectory.store import InMemoryTrajectoryStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Shared trajectory store reference
_trajectory_store: InMemoryTrajectoryStore | None = None


def set_trajectory_store(store: InMemoryTrajectoryStore) -> None:
    global _trajectory_store
    _trajectory_store = store


class ExportDatasetRequest(BaseModel):
    prompt_name: str
    input_keys: list[str]
    output_key: str = "answer"


class OptimizePromptRequest(BaseModel):
    prompt_name: str
    input_keys: list[str]
    output_key: str = "answer"
    max_bootstrapped_demos: int = 4


@router.post("/export-dspy-dataset")
async def export_dspy_dataset(request: ExportDatasetRequest) -> dict[str, Any]:
    """Export trajectory records as DSPy-compatible dataset."""
    if _trajectory_store is None:
        raise HTTPException(status_code=503, detail="trajectory store not initialized")

    try:
        from app.prompts.optimization import export_trajectory_evalset
        import dspy  # type: ignore

        records = list(_trajectory_store._records.values()) if hasattr(_trajectory_store, '_records') else []
        flat_records: list[dict[str, Any]] = []
        for rec in records:
            if isinstance(rec, dict):
                flat_records.append(rec)

        examples = export_trajectory_evalset(
            records=flat_records,
            prompt_name=request.prompt_name,
            input_keys=tuple(request.input_keys),
            output_key=request.output_key,
            dspy_module=dspy,
        )
        return {
            "prompt_name": request.prompt_name,
            "example_count": len(examples),
            "examples": [
                {"inputs": str(ex.inputs) if hasattr(ex, "inputs") else {}, "output": str(ex)}
                for ex in examples
            ],
        }
    except Exception as e:
        logger.exception("DSPy dataset export failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize-prompt")
async def optimize_prompt(request: OptimizePromptRequest) -> dict[str, Any]:
    """Trigger DSPy prompt optimization on demand."""
    if _trajectory_store is None:
        raise HTTPException(status_code=503, detail="trajectory store not initialized")

    try:
        import dspy  # type: ignore
        from app.prompts.optimization import (
            create_prompt_optimization_module,
            create_bootstrap_optimizer,
            optimize_prompt_module,
            export_trajectory_evalset,
        )
        from app.prompts.registry import PromptRegistry
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"missing dependency: {e}")

    # Export dataset
    records = list(_trajectory_store._records.values()) if hasattr(_trajectory_store, '_records') else []
    flat_records = [rec for rec in records if isinstance(rec, dict)]

    examples = export_trajectory_evalset(
        records=flat_records,
        prompt_name=request.prompt_name,
        input_keys=tuple(request.input_keys),
        output_key=request.output_key,
        dspy_module=dspy,
    )

    if len(examples) < 3:
        raise HTTPException(
            status_code=422,
            detail=f"insufficient data: got {len(examples)} examples, need at least 3",
        )

    # Split into train/eval
    split = max(1, len(examples) * 2 // 3)
    trainset = examples[:split]
    evalset = examples[split:]

    registry = PromptRegistry()
    module = create_prompt_optimization_module(
        registry, request.prompt_name, dspy_module=dspy,
    )
    metric = create_exact_match_metric(request.output_key)
    optimizer = create_bootstrap_optimizer(
        dspy_module=dspy,
        metric=metric,
        max_bootstrapped_demos=request.max_bootstrapped_demos,
    )

    result = optimize_prompt_module(
        module=module,
        optimizer=optimizer,
        trainset=trainset,
        evalset=evalset,
        metric=metric,
    )

    return {
        "prompt_name": request.prompt_name,
        "validation_score": result.validation_score,
        "compiled": result.compiled,
        "train_examples": len(trainset),
        "eval_examples": len(evalset),
    }


@router.get("/prompt-variants/{prompt_name}")
async def list_prompt_variants(prompt_name: str) -> dict[str, Any]:
    """List available prompt variants for a given prompt name."""
    try:
        from app.prompts.registry import PromptRegistry

        registry = PromptRegistry()
        template = registry.get_template(prompt_name)
        return {
            "prompt_name": prompt_name,
            "current_version": template.version if template else None,
            "variants": [],  # populated when optimization variants are registered
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"prompt '{prompt_name}' not found: {e}")
