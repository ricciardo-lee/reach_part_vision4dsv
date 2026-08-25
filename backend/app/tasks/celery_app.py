from __future__ import annotations

import asyncio
import logging

from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from celery.schedules import crontab
from tortoise import Tortoise

from app.core.config import settings

logger = logging.getLogger("app.tasks.celery")

celery_app = Celery(
    "part_vision",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.celery_app"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "cleanup-expired-images-daily": {
            "task": "images.cleanup_expired",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)


async def _with_db(coro):
    ctx = await Tortoise.init(config=settings.tortoise_config, _enable_global_fallback=True)
    try:
        return await coro
    finally:
        await Tortoise.close_connections()
        if hasattr(ctx, "__aexit__"):
            await ctx.__aexit__(None, None, None)


@celery_app.task(name="recognition.run_vision", bind=True, max_retries=1, default_retry_delay=10)
def run_vision_task(self, session_id: int) -> dict:
    from app.services.recognition import run_vision_recognition

    logger.info(
        "Celery task start | task_id=%s | session_id=%s | retries=%s | broker=%s",
        getattr(self.request, "id", None),
        session_id,
        getattr(self.request, "retries", 0),
        settings.CELERY_BROKER_URL,
    )
    try:
        asyncio.run(_with_db(run_vision_recognition(session_id)))
        logger.info("Celery task success | session_id=%s", session_id)
        return {"session_id": session_id, "ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Celery task failed | session_id=%s | error=%s", session_id, exc)
        try:
            raise self.retry(exc=exc, countdown=10)
        except MaxRetriesExceededError:
            logger.error("Celery task retries exhausted | session_id=%s", session_id)
            raise


@celery_app.task(name="images.cleanup_expired")
def cleanup_expired_images_task() -> int:
    from datetime import datetime

    from app.models import AuditLog, UploadedImage
    from app.utils.minio_client import get_storage

    async def _run() -> int:
        now = datetime.utcnow()
        images = await UploadedImage.filter(expires_at__lte=now, deleted_at=None).all()
        storage = get_storage()
        count = 0
        for image in images:
            storage.delete_object(image.object_key)
            image.deleted_at = now
            await image.save()
            count += 1
        logger.info("Cleanup expired images | count=%s", count)
        if count:
            await AuditLog.create(
                actor_type="system",
                actor_id="celery.beat",
                action="images.cleanup",
                resource_type="uploaded_image",
                resource_id=None,
                detail={"deleted_count": count, "ran_at": now.isoformat()},
            )
        return count

    return asyncio.run(_with_db(_run()))
