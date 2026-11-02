"""WhatsApp photo ingest + recognition orchestration (debounce + full vision pipeline)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from app.core.config import settings
from app.core.constants import (
    CATEGORY_EN,
    PART_IMAGE_PURPOSE,
    WHATSAPP_IMAGE_FAILED_REPLY,
    WHATSAPP_IMAGE_NOT_PART_REPLY,
    WHATSAPP_IMAGE_RECEIVED_REPLY,
    WHATSAPP_IMAGE_TOO_MANY_REPLY,
    WHATSAPP_IMAGE_UNAVAILABLE_REPLY,
)
from app.integrations.deepseek.chat import DeepSeekChatClient
from app.integrations.whatsapp.client import WhatsAppCloudClient
from app.models import (
    AppUser,
    RecognitionResult,
    RecognitionSession,
    RetrievalResult,
    UploadedImage,
    WaConversation,
    WaMessage,
)
from app.services.bootstrap import image_expiry, new_public_id
from app.services.catalog import catalog_service
from app.services.whatsapp_chat import (
    _history_messages,
    _send_and_store_outbound,
    get_active_whatsapp_prompt,
    get_or_create_contact,
    get_or_create_conversation,
    maybe_send_welcome,
)
from app.services.whatsapp_tools import TOOL_DEFINITIONS, dispatch_tool, serialize_product_out
from app.utils.images import compress_to_jpeg_bytes, compute_phash, validate_image_meta
from app.utils.minio_client import get_storage
from app.utils.redis_client import get_redis

logger = logging.getLogger(__name__)

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _session_redis_key(wa_id: str) -> str:
    return f"wa:imgsess:{wa_id}"


def _token_redis_key(session_id: int) -> str:
    return f"wa:imgtoken:{session_id}"


def category_to_english(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text in CATEGORY_EN:
        return CATEGORY_EN[text]
    lower = text.casefold()
    for key, value in CATEGORY_EN.items():
        if key.casefold() == lower:
            return value
    if CJK_RE.search(text):
        return None
    return text


_shared_app_user_id: int | None = None


async def get_shared_app_user() -> AppUser | None:
    """Resolve the shared WhatsApp H5 AppUser (e.g. Lee); cache id after first hit."""
    global _shared_app_user_id
    username = (settings.WHATSAPP_SHARED_APP_USER_USERNAME or "").strip()
    if not username:
        return None
    if _shared_app_user_id is not None:
        user = await AppUser.get_or_none(id=_shared_app_user_id, is_active=True)
        if user and user.username == username:
            return user
        _shared_app_user_id = None
    user = await AppUser.get_or_none(username=username, is_active=True)
    if user:
        _shared_app_user_id = user.id
    return user


async def _build_h5_link(session: RecognitionSession) -> str | None:
    """Deep link to H5 /wa. Auth uses shared Lee via POST /auth/wa-open (sid only)."""
    base = (settings.WHATSAPP_H5_BASE_URL or "").strip().rstrip("/")
    if not base or not session.public_id:
        return None
    shared = await get_shared_app_user()
    if shared is None:
        return None
    return f"{base}/wa?sid={session.public_id}"


def _append_h5_link(text: str, link: str | None) -> str:
    if not link:
        return text
    body = (text or "").rstrip()
    suffix = f"\n\nTap to view the 360° photos and full match details: {link}"
    return f"{body}{suffix}" if body else suffix.strip()


async def ingest_image_message(
    *,
    wa_id: str,
    profile_name: str,
    wa_message_id: str,
    media_id: str,
    mime_type: str = "",
    caption: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> None:
    contact = await get_or_create_contact(wa_id, profile_name)
    conversation, is_new = await get_or_create_conversation(contact)
    client = WhatsAppCloudClient()

    try:
        if client.configured:
            client.mark_read(wa_message_id, typing=True)
    except Exception:  # noqa: BLE001
        logger.warning("mark_read failed | message_id=%s", wa_message_id, exc_info=True)

    await maybe_send_welcome(conversation, wa_id, is_new=is_new, client=client)

    existing = await WaMessage.get_or_none(wa_message_id=wa_message_id)
    if existing:
        return

    if not media_id:
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=WHATSAPP_IMAGE_FAILED_REPLY,
            client=client,
        )
        return

    try:
        raw_bytes, content_type = client.download_media(media_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp media download failed | media_id=%s", media_id)
        await WaMessage.create(
            conversation_id=conversation.id,
            direction="in",
            wa_message_id=wa_message_id,
            msg_type="image",
            text=caption or None,
            raw_payload=raw_payload,
            media_id=media_id,
            delivery_status="received",
            error_message=str(exc)[:500],
        )
        conversation.message_count = int(conversation.message_count or 0) + 1
        conversation.last_message_at = datetime.utcnow()
        await conversation.save()
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=WHATSAPP_IMAGE_FAILED_REPLY,
            error_message=str(exc)[:500],
            client=client,
        )
        return

    try:
        validate_image_meta(
            "whatsapp.jpg",
            mime_type or content_type or "image/jpeg",
            len(raw_bytes),
            settings.max_upload_bytes,
        )
        jpeg_bytes, width, height = compress_to_jpeg_bytes(raw_bytes)
        phash = compute_phash(jpeg_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp image validate/compress failed")
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=WHATSAPP_IMAGE_FAILED_REPLY,
            error_message=str(exc)[:500],
            client=client,
        )
        return

    redis = get_redis()
    ttl_seconds = max(60, int(settings.WHATSAPP_IMAGE_SESSION_TTL_MINUTES or 10) * 60)
    pending_id_raw = redis.get(_session_redis_key(wa_id))
    session: RecognitionSession | None = None
    if pending_id_raw:
        try:
            session = await RecognitionSession.get_or_none(id=int(pending_id_raw))
        except (TypeError, ValueError):
            session = None
        if session and session.status not in {"created", "uploading"}:
            session = None

    if session is None:
        shared = await get_shared_app_user()
        session = await RecognitionSession.create(
            public_id=new_public_id(),
            status="created",
            app_user_id=shared.id if shared else None,
        )
        redis.setex(_session_redis_key(wa_id), ttl_seconds, str(session.id))
        first_image = True
    else:
        redis.setex(_session_redis_key(wa_id), ttl_seconds, str(session.id))
        first_image = False
        # Backfill ownership if an older pending session has no app_user yet.
        if session.app_user_id is None:
            shared = await get_shared_app_user()
            if shared:
                session.app_user_id = shared.id
                await session.save()

    part_count = await UploadedImage.filter(
        session_id=session.id,
        purpose=PART_IMAGE_PURPOSE,
        deleted_at=None,
    ).count()
    if part_count >= settings.MAX_IMAGES_PER_SESSION:
        await WaMessage.create(
            conversation_id=conversation.id,
            direction="in",
            wa_message_id=wa_message_id,
            msg_type="image",
            text=caption or None,
            raw_payload=raw_payload,
            media_id=media_id,
            recognition_session_id=session.id,
            delivery_status="received",
            error_message="too_many_images",
        )
        conversation.message_count = int(conversation.message_count or 0) + 1
        conversation.last_message_at = datetime.utcnow()
        await conversation.save()
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=WHATSAPP_IMAGE_TOO_MANY_REPLY,
            client=client,
            recognition_session_id=session.id,
        )
        return

    storage = get_storage()
    storage.ensure_bucket()
    object_key = f"sessions/{session.public_id}/part/{uuid.uuid4().hex}.jpg"
    storage.put_bytes(object_key, jpeg_bytes, "image/jpeg")
    await UploadedImage.create(
        session_id=session.id,
        object_key=object_key,
        content_type="image/jpeg",
        file_size=len(jpeg_bytes),
        width=width,
        height=height,
        phash=phash,
        purpose=PART_IMAGE_PURPOSE,
        sort_order=part_count,
        expires_at=image_expiry(),
    )
    session.status = "uploading"
    await session.save()

    await WaMessage.create(
        conversation_id=conversation.id,
        direction="in",
        wa_message_id=wa_message_id,
        msg_type="image",
        text=caption or None,
        raw_payload=raw_payload,
        media_id=media_id,
        object_key=object_key,
        recognition_session_id=session.id,
        delivery_status="received",
    )
    conversation.message_count = int(conversation.message_count or 0) + 1
    conversation.last_message_at = datetime.utcnow()
    await conversation.save()

    token = uuid.uuid4().hex
    debounce = max(1, int(settings.WHATSAPP_IMAGE_DEBOUNCE_SECONDS or 15))
    redis.setex(_token_redis_key(session.id), debounce + ttl_seconds, token)
    _schedule_image_recognition(session.id, token, countdown=debounce)

    if first_image:
        try:
            await _send_and_store_outbound(
                conversation=conversation,
                wa_id=wa_id,
                text=WHATSAPP_IMAGE_RECEIVED_REPLY,
                client=client,
                recognition_session_id=session.id,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to send image-received ack", exc_info=True)

    logger.info(
        "WhatsApp image ingested | wa_id=%s | session=%s | images=%s | debounce=%s",
        wa_id,
        session.public_id,
        part_count + 1,
        debounce,
    )


def _schedule_image_recognition(session_id: int, token: str, *, countdown: int) -> None:
    try:
        from app.tasks.celery_app import run_whatsapp_image_recognition_task

        run_whatsapp_image_recognition_task.apply_async(
            args=[session_id, token],
            countdown=countdown,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to schedule image recognition | session_id=%s", session_id)
        if settings.CELERY_ALLOW_INLINE_FALLBACK:
            asyncio.get_event_loop().create_task(
                _delayed_inline_recognition(session_id, token, countdown)
            )


async def _delayed_inline_recognition(session_id: int, token: str, countdown: int) -> None:
    await asyncio.sleep(max(0, countdown))
    await run_image_recognition(session_id, token)


async def run_image_recognition(session_id: int, token: str) -> None:
    redis = get_redis()
    current = redis.get(_token_redis_key(session_id))
    if current != token:
        logger.info(
            "WhatsApp image recognition skipped (stale token) | session_id=%s",
            session_id,
        )
        return

    session = await RecognitionSession.get_or_none(id=session_id)
    if session is None:
        return

    inbound = (
        await WaMessage.filter(recognition_session_id=session_id, direction="in", msg_type="image")
        .order_by("id")
        .first()
    )
    wa_id = ""
    conversation: WaConversation | None = None
    if inbound:
        conversation = await WaConversation.get(id=inbound.conversation_id).prefetch_related(
            "contact"
        )
        wa_id = conversation.contact.wa_id if conversation.contact else ""
        redis.delete(_session_redis_key(wa_id))

    client = WhatsAppCloudClient()
    if not conversation or not wa_id:
        logger.error("No conversation for recognition session | session_id=%s", session_id)
        return

    from app.tasks.dispatcher import recognition_worker_available

    if settings.CELERY_ENABLED and not recognition_worker_available():
        if not settings.CELERY_ALLOW_INLINE_FALLBACK:
            await _send_and_store_outbound(
                conversation=conversation,
                wa_id=wa_id,
                text=WHATSAPP_IMAGE_UNAVAILABLE_REPLY,
                client=client,
                recognition_session_id=session_id,
            )
            return

    captions = [
        (row.text or "").strip()
        for row in await WaMessage.filter(
            recognition_session_id=session_id, direction="in", msg_type="image"
        ).order_by("id")
        if (row.text or "").strip()
    ]
    caption = " | ".join(captions)

    try:
        from app.tasks.celery_app import run_vision_task
        from app.tasks.dispatcher import celery_workers_available

        if settings.CELERY_ENABLED and celery_workers_available():
            async_result = run_vision_task.delay(session_id)
            session.task_id = async_result.id
            await session.save()
            await _poll_recognition(session_id)
        else:
            from app.services.recognition import run_vision_recognition

            await run_vision_recognition(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp vision dispatch failed | session_id=%s", session_id)
        await _send_final_image_reply(
            conversation=conversation,
            wa_id=wa_id,
            session_id=session_id,
            text=WHATSAPP_IMAGE_FAILED_REPLY,
            client=client,
            error_message=str(exc)[:500],
        )
        return

    session = await RecognitionSession.get(id=session_id)
    if session.status == "failed":
        await _send_final_image_reply(
            conversation=conversation,
            wa_id=wa_id,
            session_id=session_id,
            text=WHATSAPP_IMAGE_FAILED_REPLY,
            client=client,
            error_message=(session.error_message or "")[:500] or None,
        )
        return
    if session.status != "done":
        # Timed out waiting; do not flip RecognitionSession.status — the vision
        # worker may still finish. Only one WhatsApp final reply is sent.
        logger.warning(
            "WhatsApp recognition wait timed out | session_id=%s | status=%s",
            session_id,
            session.status,
        )
        await _send_final_image_reply(
            conversation=conversation,
            wa_id=wa_id,
            session_id=session_id,
            text=WHATSAPP_IMAGE_FAILED_REPLY,
            client=client,
            error_message="recognition_timeout",
        )
        return

    try:
        analysis = await _build_photo_analysis(session)
        if analysis.get("not_auto_part"):
            await _send_final_image_reply(
                conversation=conversation,
                wa_id=wa_id,
                session_id=session_id,
                text=WHATSAPP_IMAGE_NOT_PART_REPLY,
                client=client,
            )
            return
        if analysis.get("unsupported_category"):
            from app.core.constants import WHATSAPP_UNSUPPORTED_CATEGORY_REPLY

            await _send_final_image_reply(
                conversation=conversation,
                wa_id=wa_id,
                session_id=session_id,
                text=WHATSAPP_UNSUPPORTED_CATEGORY_REPLY,
                client=client,
            )
            return

        image_count = await UploadedImage.filter(
            session_id=session.id,
            purpose=PART_IMAGE_PURPOSE,
            deleted_at=None,
        ).count()
        user_content = (
            f"[Photo analysis for {image_count} customer photo(s)] "
            f"{json.dumps(analysis, ensure_ascii=False)}"
        )
        if caption:
            user_content += f"\nCustomer caption: {caption}"

        system_prompt = await get_active_whatsapp_prompt()
        history = await _history_messages(
            conversation.id,
            max(1, int(settings.WHATSAPP_CONTEXT_MESSAGES or 20)),
        )
        # Drop trailing ack / empty assistant noise before injecting analysis.
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_content},
        ]
        chat = DeepSeekChatClient()

        async def _tool(name: str, arguments: dict[str, Any]) -> Any:
            return await dispatch_tool(name, arguments)

        reply, tool_trace, usage, latency_ms = await chat.chat_with_tools_async(
            messages,
            TOOL_DEFINITIONS,
            _tool,
        )
        if not (reply or "").strip():
            reply = _fallback_product_reply(analysis)
        h5_link: str | None = None
        if analysis.get("products") or analysis.get("matched_sku"):
            h5_link = await _build_h5_link(session)
            reply = _append_h5_link(reply, h5_link)
        await _send_final_image_reply(
            conversation=conversation,
            wa_id=wa_id,
            session_id=session_id,
            text=reply,
            client=client,
            tool_calls=tool_trace or None,
            token_usage=usage,
            latency_ms=latency_ms,
            h5_link=h5_link,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp photo reply failed | session_id=%s", session_id)
        await _send_final_image_reply(
            conversation=conversation,
            wa_id=wa_id,
            session_id=session_id,
            text=WHATSAPP_IMAGE_FAILED_REPLY,
            client=client,
            error_message=str(exc)[:500],
        )


def _reply_lock_key(session_id: int) -> str:
    return f"wa:imgreply:{session_id}"


async def _send_final_image_reply(
    *,
    conversation: WaConversation,
    wa_id: str,
    session_id: int,
    text: str,
    client: WhatsAppCloudClient,
    tool_calls: list[dict[str, Any]] | None = None,
    token_usage: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    error_message: str | None = None,
    h5_link: str | None = None,
) -> bool:
    """Send at most one final WhatsApp reply per recognition session."""
    redis = get_redis()
    ttl = max(600, int(settings.WHATSAPP_RECOGNITION_TIMEOUT_SECONDS or 90) * 2)
    if not redis.setnx_ex(_reply_lock_key(session_id), ttl):
        logger.info(
            "WhatsApp final image reply skipped (already sent) | session_id=%s",
            session_id,
        )
        return False
    raw_payload = {"h5_link": h5_link} if h5_link else None
    await _send_and_store_outbound(
        conversation=conversation,
        wa_id=wa_id,
        text=text,
        tool_calls=tool_calls,
        token_usage=token_usage,
        latency_ms=latency_ms,
        error_message=error_message,
        client=client,
        recognition_session_id=session_id,
        raw_payload=raw_payload,
    )
    return True


async def _poll_recognition(session_id: int) -> None:
    """Wait until recognition finishes. Does not mutate session status on timeout."""
    timeout = max(10, int(settings.WHATSAPP_RECOGNITION_TIMEOUT_SECONDS or 90))
    interval = max(0.5, float(settings.WHATSAPP_RECOGNITION_POLL_SECONDS or 2))
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        session = await RecognitionSession.get(id=session_id)
        if session.status in {"done", "failed"}:
            return
        await asyncio.sleep(interval)


async def _build_photo_analysis(session: RecognitionSession) -> dict[str, Any]:
    from app.services.category_guard import is_supported_category

    retrieval = await RetrievalResult.filter(session_id=session.id).order_by("-id").first()
    vision = await RecognitionResult.filter(session_id=session.id).order_by("-id").first()

    if vision and vision.is_auto_part is False:
        return {
            "not_auto_part": True,
            "reason": vision.reason or "",
            "detected": category_to_english(vision.part_name) or vision.part_name,
        }

    if (session.error_message or "") == "unsupported_category" or (
        vision
        and vision.is_auto_part
        and not is_supported_category(
            vision.mapped_category_code or vision.mapped_category_name or vision.part_name
        )
        and not (retrieval and retrieval.accepted)
    ):
        detected = category_to_english(
            (vision.part_name if vision else None)
            or (vision.mapped_category_name if vision else None)
        )
        return {
            "unsupported_category": True,
            "not_auto_part": False,
            "detected": detected,
            "recognition_public_id": session.public_id,
            "products": [],
            "product_count": 0,
        }

    # Auto-confirm category for vision fallback so catalog search can run.
    if (
        retrieval is None
        or (not retrieval.accepted and retrieval.decision != "category_match")
    ) and vision and vision.is_auto_part:
        category_name = vision.mapped_category_name or vision.part_name
        category_code = vision.mapped_category_code
        if category_name and not session.confirmed_category_name and is_supported_category(
            category_code or category_name
        ):
            session.confirmed_category_name = category_name
            if category_code:
                session.confirmed_category_code = category_code
            await session.save()

    products_raw: list[dict[str, Any]] = []
    try:
        if session.confirmed_category_name or (
            retrieval and (retrieval.accepted or retrieval.decision == "category_match")
        ):
            products_raw = await catalog_service.search_for_session(session)
    except Exception:  # noqa: BLE001
        logger.exception("Catalog search after WhatsApp vision failed | public_id=%s", session.public_id)
        products_raw = []

    from app.services.whatsapp_tools import _catalog_for_products

    # Convert ProductOut-like dicts via temporary objects if needed.
    class _Obj:
        def __init__(self, data: dict):
            self._data = data

        def model_dump(self) -> dict:
            return self._data

    # Strip commercial fields before LLM sees catalog products.
    _commercial_keys = ("price", "stock", "stock_status", "availability", "available")
    cleaned_raw = []
    for item in products_raw[:8]:
        row = dict(item) if isinstance(item, dict) else item
        if isinstance(row, dict):
            row = dict(row)
            for key in _commercial_keys:
                row.pop(key, None)
            attrs = row.get("attributes")
            if isinstance(attrs, dict):
                attrs = dict(attrs)
                for key in _commercial_keys:
                    attrs.pop(key, None)
                row["attributes"] = attrs
            cleaned_raw.append(row)
        else:
            cleaned_raw.append(row)

    product_objs = [_Obj(item) for item in cleaned_raw]
    catalog = await _catalog_for_products(product_objs)
    products = [serialize_product_out(item, catalog=catalog) for item in product_objs]
    for product in products:
        for key in _commercial_keys:
            product.pop(key, None)

    category = None
    if retrieval and retrieval.selected_category_cn:
        category = category_to_english(retrieval.selected_category_cn)
    if not category and session.confirmed_category_name:
        category = category_to_english(session.confirmed_category_name)
    if not category and vision:
        category = category_to_english(vision.mapped_category_name or vision.part_name)

    analysis: dict[str, Any] = {
        "not_auto_part": False,
        "recognition_public_id": session.public_id,
        "decision": None,
        "matched_sku": None,
        "score": None,
        "category": category,
        "products": products,
        "product_count": len(products),
    }
    if retrieval:
        analysis["decision"] = retrieval.decision
        analysis["matched_sku"] = retrieval.matched_sku
        analysis["score"] = retrieval.score
        analysis["accepted"] = bool(retrieval.accepted)
    if vision and vision.success:
        analysis["vision_part"] = category_to_english(vision.part_name) or category_to_english(
            vision.mapped_category_name
        )
        analysis["vision_confidence"] = vision.confidence
    return analysis


def _fallback_product_reply(analysis: dict[str, Any]) -> str:
    products = analysis.get("products") or []
    category = analysis.get("category") or analysis.get("vision_part") or "part"
    if not products:
        sku = analysis.get("matched_sku")
        if sku:
            return (
                f"I matched SKU {sku} for your photo ({category}). "
                "Please share the vehicle brand, model, and year or an OE number "
                "so I can confirm fitment."
            )
        return (
            f"I classified the photo as {category}, but found no catalog products yet. "
            "Please share an OE/part number or vehicle details."
        )
    lines = [f"Here are catalog matches for your photo ({category}):"]
    for item in products[:5]:
        name = item.get("name") or "Product"
        sku = item.get("sku") or item.get("material_code") or "-"
        lines.append(f"- {name} (SKU {sku})")
    lines.append(
        "If you share the vehicle brand/model/year or OE number, I can narrow this further."
    )
    return "\n".join(lines)
