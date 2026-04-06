"""
Legal Similarity Evidence Search - FastAPI Application
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env file before any config imports
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key, _val)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import run_bootstrap, SERVER_HOST, SERVER_PORT
from app.core.database import init_db
from app.routers.prediction import router as prediction_router
from app.routers.search import router as search_router
from app.services.session_files import session_temp_file_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: bootstrap dependencies on startup."""
    logger.info("Starting Legal Similarity Evidence Search...")

    # Run bootstrap
    logger.info("Running automatic dependency bootstrap...")
    status = run_bootstrap()

    if not status.get("all_ready", False):
        missing = [k for k, v in status.items() if not v and k != "all_ready"]
        logger.error(
            f"Bootstrap incomplete. Not ready: {', '.join(missing)}. "
            f"Search services will be unavailable until bootstrap succeeds."
        )
    else:
        logger.info("All dependencies are ready.")

        # Initialize database tables
        init_db()

        # Initialize Qdrant collections
        from app.services.vector_store import init_collections
        init_collections()

        logger.info("System fully initialized and ready.")

    yield

    session_temp_file_store.clear_all()
    logger.info("Shutting down...")


app = FastAPI(
    title="Legal Similarity Evidence Search",
    description="双层法律文书相似检索与证据溯源 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(search_router)
app.include_router(prediction_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=True,
    )
