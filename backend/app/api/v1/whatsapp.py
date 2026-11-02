"""Meta WhatsApp Cloud API webhook (mounted at /sms/whatsapp/{token})."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.integrations.whatsapp.schemas import (
    WaWebhookPayload,
    parse_inbound_messages,
    parse_statuses,
)
from app.integrations.whatsapp.signature import verify_signature
from app.services.whatsapp_chat import update_delivery_status
from app.utils.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp"])

DEDUP_TTL_SECONDS = 48 * 3600


def _path_token_ok(token: str) -> bool:
    expected = (settings.WHATSAPP_WEBHOOK_PATH_TOKEN or "").strip()
    return bool(expected) and token == expected


@router.get("/sms/whatsapp/{token}")
async def verify_webhook(token: str, request: Request) -> Response:
    if not _path_token_ok(token):
        raise HTTPException(status_code=403, detail="forbidden")
    params = request.query_params
    mode = params.get("hub.mode") or params.get("hub_mode")
    verify_token = params.get("hub.verify_token") or params.get("hub_verify_token")
    challenge = params.get("hub.challenge") or params.get("hub_challenge")
    if mode == "subscribe" and verify_token == settings.WHATSAPP_VERIFY_TOKEN and challenge is not None:
        logger.info("WhatsApp webhook verified")
        return PlainTextResponse(str(challenge), status_code=200)
    logger.warning(
        "WhatsApp verify failed | mode=%s | token_match=%s",
        mode,
        verify_token == settings.WHATSAPP_VERIFY_TOKEN,
    )
    raise HTTPException(status_code=403, detail="forbidden")


@router.post("/sms/whatsapp/{token}")
async def receive_webhook(
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if not _path_token_ok(token):
        raise HTTPException(status_code=403, detail="forbidden")

    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256") or request.headers.get(
        "x-hub-signature-256"
    )
    if settings.WHATSAPP_APP_SECRET:
        if not verify_signature(settings.WHATSAPP_APP_SECRET, raw_body, signature):
            logger.warning("WhatsApp signature verification failed")
            raise HTTPException(status_code=403, detail="forbidden")

    try:
        payload_dict = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001
        logger.warning("WhatsApp webhook invalid JSON")
        return {"success": True}

    try:
        payload = WaWebhookPayload.model_validate(payload_dict)
    except Exception:  # noqa: BLE001
        logger.warning("WhatsApp webhook schema mismatch", exc_info=True)
        return {"success": True}

    for status in parse_statuses(payload):
        try:
            await update_delivery_status(status.id, status.status)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to update delivery status | id=%s", status.id, exc_info=True)

    redis = get_redis()
    for message, profile_name in parse_inbound_messages(payload):
        dedup_key = f"wa:msg:{message.id}"
        if not redis.setnx_ex(dedup_key, DEDUP_TTL_SECONDS):
            logger.info("WhatsApp duplicate message skipped | id=%s", message.id)
            continue
        enqueue_payload = {
            "wa_id": message.from_,
            "profile_name": profile_name,
            "wa_message_id": message.id,
            "msg_type": message.type,
            "text": message.text_body,
            "media_id": message.media_id,
            "mime_type": message.mime_type,
            "caption": message.text_body if message.type == "image" else "",
            "button_id": message.button_reply_id if message.type == "interactive" else "",
            "raw_payload": message.model_dump(by_alias=True),
        }
        _dispatch_handle_message(enqueue_payload, background_tasks)

    return {"success": True}


def _dispatch_handle_message(payload: dict[str, Any], background_tasks: BackgroundTasks) -> None:
    from app.tasks.dispatcher import celery_workers_available

    if settings.CELERY_ENABLED and celery_workers_available():
        try:
            from app.tasks.celery_app import handle_whatsapp_message_task

            handle_whatsapp_message_task.delay(payload)
            logger.info(
                "WhatsApp message queued | wa_message_id=%s",
                payload.get("wa_message_id"),
            )
            return
        except Exception:  # noqa: BLE001
            logger.exception("Failed to queue WhatsApp Celery task")
            if not settings.CELERY_ALLOW_INLINE_FALLBACK:
                return

    async def _run() -> None:
        from app.services.whatsapp_chat import handle_inbound_message

        await handle_inbound_message(
            wa_id=str(payload.get("wa_id") or ""),
            profile_name=str(payload.get("profile_name") or ""),
            wa_message_id=str(payload.get("wa_message_id") or ""),
            msg_type=str(payload.get("msg_type") or "text"),
            text=str(payload.get("text") or ""),
            media_id=str(payload.get("media_id") or ""),
            mime_type=str(payload.get("mime_type") or ""),
            caption=str(payload.get("caption") or ""),
            button_id=str(payload.get("button_id") or ""),
            raw_payload=payload.get("raw_payload")
            if isinstance(payload.get("raw_payload"), dict)
            else None,
        )

    background_tasks.add_task(_run)
    logger.info(
        "WhatsApp message inline background | wa_message_id=%s",
        payload.get("wa_message_id"),
    )
