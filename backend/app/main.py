from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from tortoise.contrib.fastapi import RegisterTortoise

from app.api.v1.router import api_router
from app.api.v1.whatsapp import router as whatsapp_router
from app.core.config import ROOT_DIR, settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import register_request_logging
from app.services.bootstrap import ensure_bootstrap_data
from app.utils.minio_client import get_storage

logger = logging.getLogger("app.main")

H5_DIST_DIR = ROOT_DIR.parent / "frontend-h5" / "dist"


def _mount_h5_spa(app: FastAPI) -> None:
    """Serve built H5 under /h5 so WhatsApp links share the API ngrok host."""
    index_path = H5_DIST_DIR / "index.html"
    if not index_path.is_file():
        logger.warning(
            "H5 dist missing at %s — run: cd frontend-h5 && VITE_BASE=/h5/ npm run build",
            H5_DIST_DIR,
        )
        return

    assets_dir = H5_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/h5/assets", StaticFiles(directory=str(assets_dir)), name="h5-assets")

    index_html = index_path.read_text(encoding="utf-8")

    @app.get("/h5", include_in_schema=False)
    @app.get("/h5/", include_in_schema=False)
    async def h5_index() -> HTMLResponse:
        return HTMLResponse(index_html)

    @app.get("/h5/{full_path:path}", include_in_schema=False)
    async def h5_spa(full_path: str):
        # Static assets are mounted above; other files (e.g. favicon) may sit in dist root.
        candidate = (H5_DIST_DIR / full_path).resolve()
        try:
            candidate.relative_to(H5_DIST_DIR.resolve())
        except ValueError:
            return HTMLResponse(index_html)
        if candidate.is_file():
            return FileResponse(candidate)
        return HTMLResponse(index_html)

    logger.info("Mounted WhatsApp H5 SPA at /h5 from %s", H5_DIST_DIR)


def _is_production() -> bool:
    return (settings.APP_ENV or "").strip().lower() == "production"


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
    production = _is_production()
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
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
    app.include_router(whatsapp_router)
    _mount_h5_spa(app)

    @app.get("/health")
    async def health() -> dict:
        logger.debug("health check")
        payload = {"status": "ok", "app": settings.APP_NAME}
        if not production:
            payload["env"] = settings.APP_ENV
            payload["database"] = settings.MYSQL_DATABASE
        return payload

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

        overall = "ok" if redis_ok and celery_status in {"ok", "disabled"} else "degraded"
        whatsapp_status = {
            "enabled": bool(settings.WHATSAPP_ENABLED),
            "configured": bool(
                settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID
            ),
            "verify_token_set": bool(settings.WHATSAPP_VERIFY_TOKEN),
            "app_secret_set": bool(settings.WHATSAPP_APP_SECRET),
        }
        if production:
            # Keep probes useful without exposing infra inventory publicly.
            return {"status": overall, "whatsapp": {"enabled": whatsapp_status["enabled"]}}

        # Do NOT eagerly load DINOv2 here — that belongs in Celery workers.
        retrieval = retrieval_status()
        if not retrieval.get("ready") and settings.RETRIEVAL_ENABLED:
            retrieval = {
                **retrieval,
                "enabled": True,
                "vector_backend": settings.VECTOR_BACKEND,
                "note": "model loads lazily in Celery worker on first recognition",
            }

        return {
            "status": overall,
            "app": settings.APP_NAME,
            "database": settings.MYSQL_DATABASE,
            "redis": "ok" if redis_ok else "down",
            "celery": celery_status,
            "celery_enabled": settings.CELERY_ENABLED,
            "retrieval": retrieval,
            "whatsapp": whatsapp_status,
        }

    return app


app = create_app()
