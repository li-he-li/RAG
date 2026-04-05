"""
Reranker service using BAAI/bge-reranker-v2-m3.
Provides cross-encoder re-ranking for paragraph-level evidence.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.core.config import MODELS_CACHE_DIR, RERANKER_MODEL_NAME, resolve_torch_device

logger = logging.getLogger(__name__)

_reranker = None


def _resolve_local_snapshot(model_name: str) -> Path | None:
    model_dir = MODELS_CACHE_DIR / f"models--{model_name.replace('/', '--')}" / "snapshots"
    if not model_dir.exists():
        return None
    candidates = []
    for snap in model_dir.iterdir():
        if not snap.is_dir():
            continue
        if (snap / "config.json").exists() and (snap / "tokenizer_config.json").exists():
            candidates.append(snap)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _get_reranker():
    """Lazy-load the reranker model (singleton)."""
    global _reranker
    if _reranker is None:
        from FlagEmbedding import FlagReranker

        local_snapshot = _resolve_local_snapshot(RERANKER_MODEL_NAME)
        model_source = str(local_snapshot) if local_snapshot else RERANKER_MODEL_NAME
        device = resolve_torch_device()
        logger.info("Loading reranker model: %s on %s", model_source, device)
        _reranker = FlagReranker(
            model_source,
            cache_dir=str(MODELS_CACHE_DIR),
            use_fp16=device.startswith("cuda"),
            local_files_only=bool(local_snapshot),
            devices=device,
        )
        logger.info("Reranker model loaded on %s.", device)
    return _reranker


def rerank(
    query: str,
    passages: list[str],
    top_k: Optional[int] = None,
) -> list[tuple[int, float]]:
    """Rerank passages against a query.

    Args:
        query: The search query.
        passages: List of passage texts to rerank.
        top_k: If set, return only the top_k results.

    Returns:
        List of (original_index, score) tuples, sorted by score descending.
    """
    reranker = _get_reranker()
    pairs = [[query, p] for p in passages]
    scores = reranker.compute_score(pairs, normalize=True)

    # Handle single passage case (returns float instead of list)
    if isinstance(scores, (int, float)):
        scores = [float(scores)]
    else:
        scores = [float(s) for s in scores]

    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    if top_k is not None:
        indexed = indexed[:top_k]

    return indexed
