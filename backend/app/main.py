from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import register_request_logging
from app.services.bootstrap import ensure_bootstrap_data
from app.utils.minio_client import get_storage

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(
        "Starting %s | env=%s | db=%s | storage=%s | model=%s",
        settings.APP_NAME,
        settings.APP_ENV,
        settings.MYSQL_DATABASE,
        settings.resolved_storage_backend,
        settings.DEEPSEEK_MODEL,
    )
    async with RegisterTortoise(
        app=app,
        config=settings.tortoise_config,
        generate_schemas=True,
        _enable_global_fallback=True,
    ):
        await ensure_bootstrap_data()
        storage = get_storage()
        logger.info("Storage backend ready: %s", type(storage).__name__)
        logger.info("Application startup complete")
        yield
    logger.info("Application shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )
    register_request_logging(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict:
        logger.debug("health check")
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
            "database": settings.MYSQL_DATABASE,
        }

    @app.get("/ready")
    async def ready() -> dict:
        """Readiness: DB (via app up), Redis, Celery, and optional retrieval."""
        from app.services.retrieval_runtime import retrieval_status
        from app.tasks.dispatcher import celery_workers_available
        from app.utils.redis_client import get_redis

        redis_ok = get_redis().ping()
        if settings.CELERY_ENABLED:
            celery_status = "ok" if celery_workers_available() else "down"
        else:
            celery_status = "disabled"

        # Do NOT eagerly load DINOv2 here — that belongs in Celery workers.
        # Report last-known / config-level retrieval status only.
        retrieval = retrieval_status()
        if not retrieval.get("ready") and settings.RETRIEVAL_ENABLED:
            retrieval = {
                **retrieval,
                "enabled": True,
                "vector_backend": settings.VECTOR_BACKEND,
                "note": "model loads lazily in Celery worker on first recognition",
            }

        overall = "ok" if redis_ok and celery_status in {"ok", "disabled"} else "degraded"
        return {
            "status": overall,
            "app": settings.APP_NAME,
            "database": settings.MYSQL_DATABASE,
            "redis": "ok" if redis_ok else "down",
            "celery": celery_status,
            "celery_enabled": settings.CELERY_ENABLED,
            "retrieval": retrieval,
        }

    return app


app = create_app()
