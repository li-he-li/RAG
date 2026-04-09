"""
Shared model-cache resolution utility.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import MODELS_CACHE_DIR


def resolve_local_snapshot(model_name: str) -> Path | None:
    """Resolve latest local snapshot path for a HF model if present."""
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
