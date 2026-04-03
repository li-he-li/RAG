"""
Embedding service: supports Google Gemini Embedding API (gemini-embedding-001)
and local BAAI/bge-m3 via sentence-transformers.
Handles encoding text into vectors for both document-level and paragraph-level.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import (
    EMBEDDING_DIMENSION,
    EMBEDDING_PROVIDER,
    GOOGLE_API_KEY,
    GOOGLE_EMBEDDING_MODEL,
    MODELS_CACHE_DIR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google Embedding implementation (google-genai SDK)
# ---------------------------------------------------------------------------

_google_client = None


def _get_google_client():
    """Get or create the Google GenAI client (singleton)."""
    global _google_client
    if _google_client is None:
        from google import genai
        from google.genai import types
        _google_client = genai.Client(api_key=GOOGLE_API_KEY)
    return _google_client


def _google_encode_texts(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Encode texts using Google Gemini Embedding API with batching."""
    from google.genai import types

    client = _get_google_client()

    all_embeddings = []
    batch_size = 100  # Google API batch limit
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.models.embed_content(
            model=GOOGLE_EMBEDDING_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIMENSION,
            ),
        )
        all_embeddings.extend([e.values for e in response.embeddings])

    return all_embeddings


# ---------------------------------------------------------------------------
# Local (sentence-transformers) implementation
# ---------------------------------------------------------------------------

_local_model = None


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


def _get_local_model():
    """Lazy-load the local embedding model (singleton)."""
    global _local_model
    if _local_model is None:
        import os
        from sentence_transformers import SentenceTransformer

        model_name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
        local_snapshot = _resolve_local_snapshot(model_name)
        model_source = str(local_snapshot) if local_snapshot else model_name
        logger.info("Loading local embedding model: %s", model_source)
        _local_model = SentenceTransformer(
            model_source,
            cache_folder=str(MODELS_CACHE_DIR),
            local_files_only=bool(local_snapshot),
        )
        logger.info("Local embedding model loaded.")
    return _local_model


def _local_encode_texts(
    texts: list[str],
    batch_size: int = 32,
    normalize: bool = True,
) -> list[list[float]]:
    """Encode texts using local sentence-transformers model."""
    model = _get_local_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=normalize,
        show_progress_bar=False,
    )
    return embeddings.tolist()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encode_texts(
    texts: list[str],
    batch_size: int = 32,
    normalize: bool = True,
) -> list[list[float]]:
    """Encode a list of texts into embedding vectors.

    Automatically selects Google or local provider based on config.

    Returns:
        List of float vectors (dimension depends on provider).
    """
    if EMBEDDING_PROVIDER == "google":
        return _google_encode_texts(texts)
    return _local_encode_texts(texts, batch_size=batch_size, normalize=normalize)


def encode_single(text: str, normalize: bool = True) -> list[float]:
    """Encode a single text into an embedding vector (uses document task_type)."""
    return encode_texts([text], normalize=normalize)[0]


def encode_query(text: str) -> list[float]:
    """Encode a search query into an embedding vector.

    Uses task_type='RETRIEVAL_QUERY' for Google Embedding to optimize
    for query-side retrieval. Falls back to encode_single for local models.
    """
    if EMBEDDING_PROVIDER == "google":
        return _google_encode_texts([text], task_type="RETRIEVAL_QUERY")[0]
    return encode_single(text)
