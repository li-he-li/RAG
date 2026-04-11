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

from app.routers.trajectory import get_trajectory_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ExportDatasetRequest(BaseModel):
    prompt_name: str
    input_keys: list[str]
    output_key: str = "answer"


class OptimizePromptRequest(BaseModel):
    prompt_name: str
    input_keys: list[str]
    output_key: str = "answer"
    max_bootstrapped_demos: int = 4


def _get_store_records() -> list[dict[str, Any]]:
    """Get all records from the global trajectory store."""
    store = get_trajectory_store()
    if hasattr(store, 'records'):
        return [r for r in store.records if isinstance(r, dict)]
    return []


@router.post("/export-dspy-dataset")
async def export_dspy_dataset(request: ExportDatasetRequest) -> dict[str, Any]:
    """Export trajectory records as DSPy-compatible dataset."""
    try:
        from app.prompts.optimization import export_trajectory_evalset
        import dspy  # type: ignore

        records = _get_store_records()
        examples = export_trajectory_evalset(
            records=records,
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
    try:
        import dspy  # type: ignore
        from app.prompts.optimization import (
            create_prompt_optimization_module,
            create_bootstrap_optimizer,
            optimize_prompt_module,
            export_trajectory_evalset,
        )
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"missing dependency: {e}")

    # Export dataset from trajectory store
    records = _get_store_records()
    examples = export_trajectory_evalset(
        records=records,
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

    try:
        from app.prompts.registry import PromptRegistry
        from app.prompts.optimization import create_exact_match_metric

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

        # Register optimized variant back into PromptRegistry
        if result.compiled:
            try:
                from app.prompts.registry import PromptSegment, PromptTemplate
                from pathlib import Path

                variant_name = f"{request.prompt_name}_optimized_v{result.validation_score:.2f}"
                variant_template = PromptTemplate(
                    name=variant_name,
                    version=f"dspy-optimized-{result.validation_score:.2f}",
                    segments=(
                        PromptSegment(
                            role="system",
                            content=str(result.compiled) if result.compiled else "",
                        ),
                    ),
                    variables=tuple(request.input_keys),
                    source_path=Path("dspy://optimized"),
                )
                registry._templates[variant_name] = variant_template
                logger.info("Registered optimized prompt variant: %s (score=%.3f)", variant_name, result.validation_score)
            except Exception as reg_exc:
                logger.warning("Failed to register optimized variant: %s", reg_exc)

        return {
            "prompt_name": request.prompt_name,
            "validation_score": result.validation_score,
            "compiled": result.compiled is not None,
            "variant_name": f"{request.prompt_name}_optimized_v{result.validation_score:.2f}" if result.compiled else None,
            "train_examples": len(trainset),
            "eval_examples": len(evalset),
        }
    except Exception as e:
        logger.exception("DSPy optimization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompt-variants/{prompt_name}")
async def list_prompt_variants(prompt_name: str) -> dict[str, Any]:
    """List available prompt variants for a given prompt name."""
    try:
        from app.prompts.registry import PromptRegistry

        registry = PromptRegistry()
        variants = []
        for name, template in registry._templates.items():
            if name.startswith(prompt_name):
                variants.append({
                    "name": name,
                    "version": template.version,
                })
        current = registry._templates.get(prompt_name)
        return {
            "prompt_name": prompt_name,
            "current_version": current.version if current else None,
            "variants": variants,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"prompt '{prompt_name}' not found: {e}")
