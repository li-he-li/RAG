"""
Legal Similarity Evidence Search - FastAPI Application
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import (
    get_cors_middleware_kwargs,
    MAX_JSON_BODY_BYTES,
    RATE_LIMIT_PER_MINUTE,
    run_bootstrap,
    SERVER_HOST,
    SERVER_PORT,
    TRUSTED_HOSTS,
    warn_insecure_defaults,
)
from app.middleware.api_key import APIKeyMiddleware
from app.middleware.max_json_body import MaxJsonBodyMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.analytics.middleware import CorrelationIdMiddleware
from app.core.database import init_db
from app.routers.prediction import router as prediction_router
from app.routers.search import router as search_router
from app.agents.robustness import (
    DirtyStateCleaner,
    RobustnessManager,
    background_task_tracker,
    idempotent_request_cache,
)
from app.services.session_files import session_temp_file_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
robustness_manager = RobustnessManager(
    idempotent_cache=idempotent_request_cache,
    task_tracker=background_task_tracker,
    dirty_state_cleaner=DirtyStateCleaner(temp_roots=(Path(".tmp"),), ttl_seconds=4 * 60 * 60),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: bootstrap dependencies on startup."""
    logger.info("Starting Legal Similarity Evidence Search...")
    warn_insecure_defaults()

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

    robustness_manager.schedule_startup_cleanup(active_session_ids=set())
    yield

    await background_task_tracker.shutdown()
    session_temp_file_store.clear_all()
    logger.info("Shutting down...")


app = FastAPI(
    title="Legal Similarity Evidence Search",
    description="双层法律文书相似检索与证据溯源 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS (see CORS_ALLOW_ORIGINS in .env; never use credentials with allow_origins=*)
app.add_middleware(CORSMiddleware, **get_cors_middleware_kwargs())
# Optional shared secret for /api/* when API_KEY is set (OPTIONS exempt; see SECURITY.md)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, per_minute=RATE_LIMIT_PER_MINUTE)
app.add_middleware(MaxJsonBodyMiddleware, max_bytes=MAX_JSON_BODY_BYTES)
if TRUSTED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=TRUSTED_HOSTS)

# Include routers — versioned prefix (/api/v1/*) is canonical
app.include_router(search_router, prefix="/api/v1")
app.include_router(prediction_router, prefix="/api/v1")

# Backward-compatible unversioned mount (remove after all clients migrated)
app.include_router(search_router, prefix="/api")
app.include_router(prediction_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=True,
    )
