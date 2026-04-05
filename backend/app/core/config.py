"""
Bootstrap and configuration management.
Handles automatic provisioning of PostgreSQL, Qdrant, and embedding models.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # E:\fl app\backend
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
MODELS_CACHE_DIR = DATA_DIR / "models_cache"

# ---------------------------------------------------------------------------
# PostgreSQL config
# ---------------------------------------------------------------------------

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "legalsearch")
PG_PASSWORD = os.getenv("PG_PASSWORD", "legalsearch")
PG_DATABASE = os.getenv("PG_DATABASE", "legal_search")

PG_DOCKER_NAME = "legal-search-postgres"
PG_DOCKER_IMAGE = "postgres:16-alpine"

DATABASE_URL = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"

# ---------------------------------------------------------------------------
# Qdrant config
# ---------------------------------------------------------------------------

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_DOCKER_NAME = "legal-search-qdrant"
QDRANT_DOCKER_IMAGE = "qdrant/qdrant:latest"

# Collection names
DOC_COLLECTION = "legal_documents"
PARA_COLLECTION = "legal_paragraphs"

# ---------------------------------------------------------------------------
# Embedding model config
# ---------------------------------------------------------------------------

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "google")  # "google" or "local"
RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
TORCH_DEVICE = os.getenv("TORCH_DEVICE", "auto").strip().lower()

# Google Embedding config
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_EMBEDDING_MODEL = os.getenv("GOOGLE_EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSION = 768  # gemini-embedding-001 with output_dimensionality=768

# ---------------------------------------------------------------------------
# DeepSeek LLM config (for match explanation generation)
# ---------------------------------------------------------------------------

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-58ec91886fa144998d036de19412cc13")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ---------------------------------------------------------------------------
# Server config
# ---------------------------------------------------------------------------

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# ---------------------------------------------------------------------------
# Retrieval rollout / fallback config
# ---------------------------------------------------------------------------


def _as_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def torch_cuda_available() -> bool:
    """Return whether the current runtime can use CUDA."""
    try:
        import torch
    except Exception:
        return False
    return bool(torch.cuda.is_available())


def resolve_torch_device() -> str:
    """Resolve the runtime device for local model inference."""
    if TORCH_DEVICE not in {"auto", "cpu", "cuda", "cuda:0"}:
        return "cuda:0" if torch_cuda_available() else "cpu"
    if TORCH_DEVICE == "cpu":
        return "cpu"
    if TORCH_DEVICE in {"cuda", "cuda:0"}:
        return "cuda:0" if torch_cuda_available() else "cpu"
    return "cuda:0" if torch_cuda_available() else "cpu"


_ROLLOUT_ALLOWED_STAGES = {"document_only", "dual_no_explain", "dual_full"}
RETRIEVAL_ROLLOUT_STAGE = os.getenv("RETRIEVAL_ROLLOUT_STAGE", "dual_full").strip().lower()
if RETRIEVAL_ROLLOUT_STAGE not in _ROLLOUT_ALLOWED_STAGES:
    RETRIEVAL_ROLLOUT_STAGE = "dual_full"

RETRIEVAL_ENABLE_FALLBACK = _as_bool(
    os.getenv("RETRIEVAL_ENABLE_FALLBACK", "true"),
    default=True,
)

# Runtime bootstrap status cache (updated by run_bootstrap).
_BOOTSTRAP_STATUS: dict[str, bool] = {
    "postgresql_ready": False,
    "qdrant_ready": False,
    "embedding_model_ready": False,
    "reranker_model_ready": False,
    "all_ready": False,
}


def get_bootstrap_status() -> dict[str, bool]:
    """Return a snapshot of the latest bootstrap status."""
    return dict(_BOOTSTRAP_STATUS)


def get_bootstrap_missing_components() -> list[str]:
    """Return a list of dependency names that are not ready."""
    mapping = [
        ("postgresql_ready", "PostgreSQL"),
        ("qdrant_ready", "Qdrant"),
        ("embedding_model_ready", "Embedding Model"),
        ("reranker_model_ready", "Reranker Model"),
    ]
    return [name for key, name in mapping if not _BOOTSTRAP_STATUS.get(key, False)]


def _docker_is_running() -> bool:
    """Check if Docker daemon is accessible."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _resolve_local_model_snapshot(model_name: str) -> Path | None:
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


def _container_exists(name: str) -> bool:
    """Check if a Docker container exists (running or stopped)."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    return name in result.stdout.strip().splitlines()


def _container_is_running(name: str) -> bool:
    """Check if a Docker container is running."""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    return name in result.stdout.strip().splitlines()


def _start_container(name: str) -> bool:
    """Start an existing Docker container."""
    result = subprocess.run(
        ["docker", "start", name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def bootstrap_postgresql() -> bool:
    """Start or create a PostgreSQL container for the service."""
    if not _docker_is_running():
        logger.error("Docker is not running. Please start Docker first.")
        return False

    if _container_is_running(PG_DOCKER_NAME):
        logger.info(f"PostgreSQL container '{PG_DOCKER_NAME}' is already running.")
        return True

    if _container_exists(PG_DOCKER_NAME):
        logger.info(f"Starting existing PostgreSQL container '{PG_DOCKER_NAME}'...")
        return _start_container(PG_DOCKER_NAME)

    logger.info(f"Creating and starting PostgreSQL container '{PG_DOCKER_NAME}'...")
    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", PG_DOCKER_NAME,
            "-e", f"POSTGRES_USER={PG_USER}",
            "-e", f"POSTGRES_PASSWORD={PG_PASSWORD}",
            "-e", f"POSTGRES_DB={PG_DATABASE}",
            "-p", f"{PG_PORT}:5432",
            PG_DOCKER_IMAGE,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Failed to start PostgreSQL: {result.stderr}")
        return False

    # Wait for PostgreSQL to be ready
    logger.info("Waiting for PostgreSQL to be ready...")
    for _ in range(30):
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=PG_HOST, port=PG_PORT,
                user=PG_USER, password=PG_PASSWORD,
                dbname=PG_DATABASE,
            )
            conn.close()
            logger.info("PostgreSQL is ready.")
            return True
        except Exception:
            time.sleep(1)

    logger.error("PostgreSQL did not become ready in time.")
    return False


def bootstrap_qdrant() -> bool:
    """Start or create a Qdrant container for the service."""
    if not _docker_is_running():
        logger.error("Docker is not running. Please start Docker first.")
        return False

    if _container_is_running(QDRANT_DOCKER_NAME):
        logger.info(f"Qdrant container '{QDRANT_DOCKER_NAME}' is already running.")
        return True

    if _container_exists(QDRANT_DOCKER_NAME):
        logger.info(f"Starting existing Qdrant container '{QDRANT_DOCKER_NAME}'...")
        return _start_container(QDRANT_DOCKER_NAME)

    logger.info(f"Creating and starting Qdrant container '{QDRANT_DOCKER_NAME}'...")
    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", QDRANT_DOCKER_NAME,
            "-p", f"{QDRANT_PORT}:6333",
            "-p", "6334:6334",
            QDRANT_DOCKER_IMAGE,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Failed to start Qdrant: {result.stderr}")
        return False

    # Wait for Qdrant to be ready
    logger.info("Waiting for Qdrant to be ready...")
    import requests
    for _ in range(30):
        try:
            resp = requests.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/healthz")
            if resp.status_code == 200:
                logger.info("Qdrant is ready.")
                return True
        except Exception:
            pass
        time.sleep(1)

    logger.error("Qdrant did not become ready in time.")
    return False


def bootstrap_embedding_model() -> bool:
    """Validate the embedding model is ready."""
    if EMBEDDING_PROVIDER == "google":
        return _bootstrap_google_embedding()
    return _bootstrap_local_embedding()


def _bootstrap_google_embedding() -> bool:
    """Validate Google Embedding API access."""
    try:
        from google import genai
        from google.genai import types
        if not GOOGLE_API_KEY:
            logger.error("GOOGLE_API_KEY is not set.")
            return False
        client = genai.Client(api_key=GOOGLE_API_KEY)
        # Quick test
        result = client.models.embed_content(
            model=GOOGLE_EMBEDDING_MODEL,
            contents="测试",
            config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSION),
        )
        if result.embeddings and result.embeddings[0].values:
            logger.info("Google Embedding API is ready (model: %s).", GOOGLE_EMBEDDING_MODEL)
            return True
        logger.error("Google Embedding API returned empty result.")
        return False
    except Exception as e:
        logger.error(f"Failed to validate Google Embedding API: {e}")
        return False


def _bootstrap_local_embedding() -> bool:
    """Download and cache the local embedding model."""
    try:
        local_model_name = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
        from sentence_transformers import SentenceTransformer
        local_snapshot = _resolve_local_model_snapshot(local_model_name)
        model_source = str(local_snapshot) if local_snapshot else local_model_name
        logger.info("Loading embedding model '%s'...", model_source)
        model = SentenceTransformer(
            model_source,
            cache_folder=str(MODELS_CACHE_DIR),
            local_files_only=bool(local_snapshot),
        )
        _ = model.encode(["测试"], normalize_embeddings=True)
        logger.info("Embedding model is ready.")
        return True
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        return False


def bootstrap_reranker_model() -> bool:
    """Download and cache the BAAI/bge-reranker-v2-m3 model."""
    try:
        from FlagEmbedding import FlagReranker
        local_snapshot = _resolve_local_model_snapshot(RERANKER_MODEL_NAME)
        model_source = str(local_snapshot) if local_snapshot else RERANKER_MODEL_NAME
        device = resolve_torch_device()
        logger.info("Loading reranker model '%s' on %s...", model_source, device)
        reranker = FlagReranker(
            model_source,
            cache_dir=str(MODELS_CACHE_DIR),
            use_fp16=device.startswith("cuda"),
            local_files_only=bool(local_snapshot),
            devices=device,
        )
        # Quick test
        _ = reranker.compute_score(["测试", "测试"])
        logger.info("Reranker model is ready.")
        return True
    except Exception as e:
        logger.error(f"Failed to load reranker model: {e}")
        return False


def run_bootstrap() -> dict[str, bool]:
    """
    Run the full bootstrap sequence.
    Returns a dict of component -> ready status.
    """
    os.makedirs(str(DOCUMENTS_DIR), exist_ok=True)
    os.makedirs(str(MODELS_CACHE_DIR), exist_ok=True)

    status = {
        "postgresql_ready": False,
        "qdrant_ready": False,
        "embedding_model_ready": False,
        "reranker_model_ready": False,
    }

    logger.info("=" * 60)
    logger.info("Starting automatic dependency bootstrap...")
    logger.info("=" * 60)

    status["postgresql_ready"] = bootstrap_postgresql()
    status["qdrant_ready"] = bootstrap_qdrant()
    status["embedding_model_ready"] = bootstrap_embedding_model()
    status["reranker_model_ready"] = bootstrap_reranker_model()

    status["all_ready"] = all(status.values())

    global _BOOTSTRAP_STATUS
    _BOOTSTRAP_STATUS = dict(status)
    return status
