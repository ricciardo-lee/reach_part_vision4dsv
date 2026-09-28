from __future__ import annotations

import logging

from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger("app.tasks.dispatcher")


def celery_workers_available() -> bool:
    """Return True only when at least one Celery worker responds to ping."""
    try:
        from app.tasks.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        ping = inspector.ping() if inspector else None
        available = bool(ping)
        logger.info("Celery worker ping | available=%s | detail=%s", available, ping)
        return available
    except Exception as exc:  # noqa: BLE001
        logger.warning("Celery worker check failed: %s", exc)
        return False


async def dispatch_vision_recognition(session_id: int, public_id: str) -> str:
    """
    Preferred path: queue recognition to Celery.
    Returns: 'celery' | 'inline'
    """
    if settings.CELERY_ENABLED:
        if celery_workers_available():
            from app.models import RecognitionSession
            from app.tasks.celery_app import run_vision_task

            async_result = run_vision_task.delay(session_id)
            session = await RecognitionSession.get(id=session_id)
            session.task_id = async_result.id
            await session.save()
            logger.info(
                "Recognition queued to Celery | public_id=%s | task_id=%s | broker=%s",
                public_id,
                async_result.id,
                settings.CELERY_BROKER_URL,
            )
            return "celery"

        if not settings.CELERY_ALLOW_INLINE_FALLBACK:
            logger.error(
                "Celery enabled but no worker online | public_id=%s | broker=%s",
                public_id,
                settings.CELERY_BROKER_URL,
            )
            raise AppError(
                "识别队列未就绪：请先启动本地 Celery worker"
                "（cd backend && PYTHONPATH=. celery -A app.tasks.celery_app.celery_app worker -l info）",
                code="celery_unavailable",
                status_code=503,
            )
        logger.warning(
            "No Celery worker, fallback inline | public_id=%s",
            public_id,
        )

    from app.services.recognition import run_vision_recognition

    logger.info(
        "Recognition run inline | public_id=%s | CELERY_ENABLED=%s",
        public_id,
        settings.CELERY_ENABLED,
    )
    try:
        await run_vision_recognition(session_id)
    except Exception as exc:  # noqa: BLE001
        # Failure already persisted on the session by run_vision_recognition.
        logger.warning("Inline recognition failed | public_id=%s | error=%s", public_id, exc)
    return "inline"


async def dispatch_vision_fallback_only(session_id: int, public_id: str) -> str:
    """Queue or run DeepSeek-only path (skip SKU retrieval)."""
    if settings.CELERY_ENABLED and celery_workers_available():
        from app.models import RecognitionSession
        from app.tasks.celery_app import run_vision_fallback_task

        async_result = run_vision_fallback_task.delay(session_id)
        session = await RecognitionSession.get(id=session_id)
        session.task_id = async_result.id
        await session.save()
        logger.info(
            "Vision fallback queued | public_id=%s | task_id=%s",
            public_id,
            async_result.id,
        )
        return "celery"

    if settings.CELERY_ENABLED and not settings.CELERY_ALLOW_INLINE_FALLBACK:
        raise AppError(
            "识别队列未就绪：请先启动本地 Celery worker",
            code="celery_unavailable",
            status_code=503,
        )

    from app.services.recognition import run_vision_fallback_only

    try:
        await run_vision_fallback_only(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Inline vision fallback failed | public_id=%s | error=%s", public_id, exc)
    return "inline"
