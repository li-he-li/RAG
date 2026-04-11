"""
Bootstrap and configuration management.
Handles automatic provisioning of PostgreSQL, Qdrant, and embedding models.

Configuration is validated via pydantic-settings at import time.
Invalid env vars (e.g. PG_PORT=abc) produce a clear ValidationError.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths (not from env – derived from file location)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # E:\fl app\backend
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
MODELS_CACHE_DIR = DATA_DIR / "models_cache"


# ---------------------------------------------------------------------------
# Typed Settings model
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """All runtime configuration, validated at import time."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",          # ignore unknown keys in .env
        env_ignore_empty=False,
    )

    # -- PostgreSQL ----------------------------------------------------------
    PG_HOST: str = "localhost"
    PG_PORT: int = Field(default=5432, ge=1, le=65535)
    PG_USER: str = "legalsearch"
    PG_PASSWORD: str = "legalsearch"
    PG_DATABASE: str = "legal_search"

    PG_DOCKER_NAME: str = "legal-search-postgres"
    PG_DOCKER_IMAGE: str = "postgres:16-alpine"

    # -- Qdrant --------------------------------------------------------------
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = Field(default=6333, ge=1, le=65535)
    QDRANT_DOCKER_NAME: str = "legal-search-qdrant"
    QDRANT_DOCKER_IMAGE: str = "qdrant/qdrant:v1.13.4"

    # Collection names
    DOC_COLLECTION: str = "legal_documents"
    PARA_COLLECTION: str = "legal_paragraphs"

    # -- Embedding -----------------------------------------------------------
    EMBEDDING_PROVIDER: Literal["google", "local"] = "google"
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"
    TORCH_DEVICE: str = "auto"

    # Google Embedding
    GOOGLE_API_KEY: str = ""
    GOOGLE_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    EMBEDDING_DIMENSION: int = 768

    # Local embedding (used only when EMBEDDING_PROVIDER=local)
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"

    # -- DeepSeek LLM -------------------------------------------------------
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # -- Server --------------------------------------------------------------
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = Field(default=8000, ge=1, le=65535)
    DEBUG: bool = False

    # -- HTTP security -------------------------------------------------------
    API_KEY: str = ""
    MAX_UPLOAD_BYTES: int = Field(default=50 * 1024 * 1024, ge=1024)
    RATE_LIMIT_PER_MINUTE: int = Field(default=120, ge=0)
    MAX_JSON_BODY_BYTES: int = Field(default=8 * 1024 * 1024, ge=1024)
    TRUSTED_HOSTS_RAW: str = Field(default="", alias="TRUSTED_HOSTS")

    # -- CORS ----------------------------------------------------------------
    CORS_ALLOW_ORIGINS_RAW: str = Field(default="", alias="CORS_ALLOW_ORIGINS")
    CORS_ALLOW_CREDENTIALS: bool = True

    # -- Retrieval rollout ---------------------------------------------------
    RETRIEVAL_ROLLOUT_STAGE: Literal["document_only", "dual_no_explain", "dual_full"] = "dual_full"
    RETRIEVAL_ENABLE_FALLBACK: bool = True

    # -- Validation ----------------------------------------------------------

    @field_validator("TORCH_DEVICE", mode="before")
    @classmethod
    def _normalize_torch_device(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Singleton instance (validates at import time)
# ---------------------------------------------------------------------------

_settings = Settings()

# Re-export individual values so existing `from app.core.config import X` works.
PG_HOST = _settings.PG_HOST
PG_PORT = _settings.PG_PORT
PG_USER = _settings.PG_USER
PG_PASSWORD = _settings.PG_PASSWORD
PG_DATABASE = _settings.PG_DATABASE
PG_DOCKER_NAME = _settings.PG_DOCKER_NAME
PG_DOCKER_IMAGE = _settings.PG_DOCKER_IMAGE

DATABASE_URL = (
    f"postgresql://{_settings.PG_USER}:{_settings.PG_PASSWORD}"
    f"@{_settings.PG_HOST}:{_settings.PG_PORT}/{_settings.PG_DATABASE}"
)

QDRANT_HOST = _settings.QDRANT_HOST
QDRANT_PORT = _settings.QDRANT_PORT
QDRANT_DOCKER_NAME = _settings.QDRANT_DOCKER_NAME
QDRANT_DOCKER_IMAGE = _settings.QDRANT_DOCKER_IMAGE
DOC_COLLECTION = _settings.DOC_COLLECTION
PARA_COLLECTION = _settings.PARA_COLLECTION

EMBEDDING_PROVIDER = _settings.EMBEDDING_PROVIDER
RERANKER_MODEL_NAME = _settings.RERANKER_MODEL_NAME
TORCH_DEVICE = _settings.TORCH_DEVICE
GOOGLE_API_KEY = _settings.GOOGLE_API_KEY
GOOGLE_EMBEDDING_MODEL = _settings.GOOGLE_EMBEDDING_MODEL
EMBEDDING_DIMENSION = _settings.EMBEDDING_DIMENSION
EMBEDDING_MODEL_NAME = _settings.EMBEDDING_MODEL_NAME

DEEPSEEK_API_KEY = _settings.DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL = _settings.DEEPSEEK_BASE_URL
DEEPSEEK_MODEL = _settings.DEEPSEEK_MODEL

SERVER_HOST = _settings.SERVER_HOST
SERVER_PORT = _settings.SERVER_PORT
DEBUG = _settings.DEBUG

API_KEY = _settings.API_KEY
MAX_UPLOAD_BYTES = _settings.MAX_UPLOAD_BYTES
RATE_LIMIT_PER_MINUTE = _settings.RATE_LIMIT_PER_MINUTE
MAX_JSON_BODY_BYTES = _settings.MAX_JSON_BODY_BYTES
TRUSTED_HOSTS = [h.strip() for h in _settings.TRUSTED_HOSTS_RAW.split(",") if h.strip()]

RETRIEVAL_ROLLOUT_STAGE = _settings.RETRIEVAL_ROLLOUT_STAGE
RETRIEVAL_ENABLE_FALLBACK = _settings.RETRIEVAL_ENABLE_FALLBACK


# ---------------------------------------------------------------------------
# CORS helper
# ---------------------------------------------------------------------------

def get_cors_middleware_kwargs() -> dict:
    """Build Starlette CORSMiddleware kwargs; avoids allow_credentials=True with allow_origins=['*']."""
    raw = _settings.CORS_ALLOW_ORIGINS_RAW.strip()
    if not raw:
        allow_origins = [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1:5500",
            "http://localhost:5500",
        ]
        return {
            "allow_origins": allow_origins,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    if raw == "*":
        return {
            "allow_origins": ["*"],
            "allow_credentials": False,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    allow_origins = [x.strip() for x in raw.split(",") if x.strip()]
    return {
        "allow_origins": allow_origins,
        "allow_credentials": _settings.CORS_ALLOW_CREDENTIALS,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


def warn_insecure_defaults() -> None:
    """Log once per process if dangerous defaults are in use."""
    if PG_PASSWORD == "legalsearch":
        logger.warning(
            "PG_PASSWORD is still the default 'legalsearch'. "
            "Set a strong password and restrict database network access for production."
        )


# ---------------------------------------------------------------------------
# Torch device helpers
# ---------------------------------------------------------------------------

def torch_cuda_available() -> bool:
    """Return whether the current runtime can use CUDA."""
    try:
        import torch
    except Exception:
        return False
    return bool(torch.cuda.is_available())


def resolve_torch_device() -> str:
    """Resolve the runtime device for local model inference."""
    device = TORCH_DEVICE
    if device not in {"auto", "cpu", "cuda", "cuda:0"}:
        return "cuda:0" if torch_cuda_available() else "cpu"
    if device == "cpu":
        return "cpu"
    return "cuda:0" if torch_cuda_available() else "cpu"


# ---------------------------------------------------------------------------
# Bootstrap status tracking
# ---------------------------------------------------------------------------

_BOOTSTRAP_STATUS: dict[str, bool] = {
    "postgresql_ready": False,
    "qdrant_ready": False,
    "embedding_model_ready": False,
    "reranker_model_ready": False,
    "all_ready": False,
}

_BOOTSTRAP_COMPONENT_LABELS: tuple[tuple[str, str], ...] = (
    ("postgresql_ready", "PostgreSQL"),
    ("qdrant_ready", "Qdrant"),
    ("embedding_model_ready", "Embedding Model"),
    ("reranker_model_ready", "Reranker Model"),
)


def get_bootstrap_status() -> dict[str, bool]:
    """Return a snapshot of the latest bootstrap status."""
    return dict(_BOOTSTRAP_STATUS)


def get_bootstrap_missing_components(status: dict[str, bool] | None = None) -> list[str]:
    """Return a list of dependency names that are not ready."""
    source = _BOOTSTRAP_STATUS if status is None else status
    return [name for key, name in _BOOTSTRAP_COMPONENT_LABELS if not source.get(key, False)]


def _probe_postgresql_readiness() -> bool:
    """Perform a live PostgreSQL readiness probe."""
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            dbname=PG_DATABASE,
        )
        conn.close()
        return True
    except Exception:
        return False


def _probe_qdrant_readiness() -> bool:
    """Perform a live Qdrant readiness probe."""
    try:
        import httpx

        resp = httpx.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/healthz", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _probe_embedding_model_readiness() -> bool:
    """Perform a live embedding provider readiness probe."""
    try:
        if EMBEDDING_PROVIDER == "google":
            from app.services.embedding import _get_google_client

            _get_google_client()
        else:
            from app.services.embedding import _get_local_model

            _get_local_model()
        return True
    except Exception:
        return False


def _probe_reranker_model_readiness() -> bool:
    """Perform a live reranker readiness probe."""
    try:
        from app.services.reranker import _get_reranker

        _get_reranker()
        return True
    except Exception:
        return False


def probe_bootstrap_status(*, refresh_snapshot: bool = False) -> dict[str, bool]:
    """Return a live readiness snapshot shared by health checks and retrieval gating."""
    status = {
        "postgresql_ready": _probe_postgresql_readiness(),
        "qdrant_ready": _probe_qdrant_readiness(),
        "embedding_model_ready": _probe_embedding_model_readiness(),
        "reranker_model_ready": _probe_reranker_model_readiness(),
    }
    status["all_ready"] = all(status.values())

    if refresh_snapshot:
        global _BOOTSTRAP_STATUS
        _BOOTSTRAP_STATUS = dict(status)

    return status


# ---------------------------------------------------------------------------
# Docker / Bootstrap helpers
# ---------------------------------------------------------------------------

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
    import httpx
    for _ in range(30):
        try:
            resp = httpx.get(f"http://{QDRANT_HOST}:{QDRANT_PORT}/healthz", timeout=3)
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
        from sentence_transformers import SentenceTransformer
        local_snapshot = _resolve_local_model_snapshot(EMBEDDING_MODEL_NAME)
        model_source = str(local_snapshot) if local_snapshot else EMBEDDING_MODEL_NAME
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
