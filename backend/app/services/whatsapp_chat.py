"""WhatsApp conversation orchestration: contact/session, LLM tools, outbound send."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.config import settings
from app.core.constants import (
    DEFAULT_WHATSAPP_CHAT_PROMPT,
    WHATSAPP_ERROR_FALLBACK_REPLY,
    WHATSAPP_GUIDE_REPLIES,
    WHATSAPP_RATE_LIMIT_REPLY,
    WHATSAPP_UNSUPPORTED_MEDIA_REPLY,
    WHATSAPP_WELCOME_BODY,
    WHATSAPP_WELCOME_BUTTONS,
)
from app.core.exceptions import RateLimitError
from app.integrations.deepseek.chat import DeepSeekChatClient
from app.integrations.whatsapp.client import WhatsAppCloudClient
from app.models import PromptConfig, WaContact, WaConversation, WaMessage
from app.services.whatsapp_tools import TOOL_DEFINITIONS, dispatch_tool
from app.utils.redis_client import get_redis

logger = logging.getLogger(__name__)


async def get_active_whatsapp_prompt() -> str:
    row = (
        await PromptConfig.filter(purpose="whatsapp_chat", is_active=True)
        .order_by("-id")
        .first()
    )
    content = (row.content if row else "") or ""
    return content.strip() or DEFAULT_WHATSAPP_CHAT_PROMPT


async def get_or_create_contact(wa_id: str, profile_name: str = "") -> WaContact:
    contact = await WaContact.get_or_none(wa_id=wa_id)
    now = datetime.utcnow()
    if contact is None:
        contact = await WaContact.create(
            wa_id=wa_id,
            profile_name=(profile_name or "")[:128],
            last_seen_at=now,
        )
        return contact
    changed = False
    if profile_name and profile_name != contact.profile_name:
        contact.profile_name = profile_name[:128]
        changed = True
    contact.last_seen_at = now
    changed = True
    if changed:
        await contact.save()
    return contact


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


async def get_or_create_conversation(contact: WaContact) -> tuple[WaConversation, bool]:
    """Return (conversation, is_new). New after first contact or idle timeout close."""
    idle_hours = max(1, int(settings.WHATSAPP_CONVERSATION_IDLE_HOURS or 24))
    cutoff = datetime.utcnow() - timedelta(hours=idle_hours)
    conversation = (
        await WaConversation.filter(contact_id=contact.id, status="open")
        .order_by("-id")
        .first()
    )
    last_at = _naive_utc(conversation.last_message_at) if conversation else None
    if conversation and last_at and last_at >= cutoff:
        return conversation, False
    if conversation and last_at and last_at < cutoff:
        conversation.status = "closed"
        await conversation.save()
    created = await WaConversation.create(
        contact_id=contact.id,
        status="open",
        last_message_at=datetime.utcnow(),
        message_count=0,
        llm_tokens=0,
        welcome_sent_at=None,
    )
    return created, True


async def store_inbound_message(
    *,
    conversation: WaConversation,
    wa_message_id: str,
    msg_type: str,
    text: Optional[str],
    raw_payload: dict[str, Any] | None,
) -> WaMessage:
    existing = await WaMessage.get_or_none(wa_message_id=wa_message_id)
    if existing:
        return existing
    message = await WaMessage.create(
        conversation_id=conversation.id,
        direction="in",
        wa_message_id=wa_message_id,
        msg_type=msg_type or "text",
        text=text,
        raw_payload=raw_payload,
        delivery_status="received",
    )
    conversation.message_count = int(conversation.message_count or 0) + 1
    conversation.last_message_at = datetime.utcnow()
    await conversation.save()
    return message


async def update_delivery_status(wa_message_id: str, status: str) -> bool:
    message = await WaMessage.get_or_none(wa_message_id=wa_message_id)
    if message is None:
        return False
    message.delivery_status = status
    await message.save()
    return True


async def maybe_send_welcome(
    conversation: WaConversation,
    wa_id: str,
    *,
    is_new: bool,
    client: WhatsAppCloudClient | None = None,
) -> bool:
    """Send welcome interactive card once per new conversation. Returns True if sent."""
    if not is_new:
        return False
    await conversation.refresh_from_db()
    if conversation.welcome_sent_at is not None:
        return False

    client = client or WhatsAppCloudClient()
    message_ids: list[str] = []
    send_error: str | None = None
    try:
        if client.configured:
            message_ids = client.send_interactive_buttons(
                wa_id,
                WHATSAPP_WELCOME_BODY,
                WHATSAPP_WELCOME_BUTTONS,
            )
        else:
            logger.warning("WhatsApp client not configured; storing welcome without send")
            send_error = "whatsapp_not_configured"
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp welcome send failed | wa_id=%s", wa_id)
        send_error = str(exc)[:500]

    primary_id = message_ids[0] if message_ids else None
    await WaMessage.create(
        conversation_id=conversation.id,
        direction="out",
        wa_message_id=primary_id,
        msg_type="interactive",
        text=WHATSAPP_WELCOME_BODY,
        raw_payload={"buttons": list(WHATSAPP_WELCOME_BUTTONS)},
        delivery_status="sent" if primary_id else "failed",
        error_message=send_error,
    )
    now = datetime.utcnow()
    conversation.welcome_sent_at = now
    conversation.message_count = int(conversation.message_count or 0) + 1
    conversation.last_message_at = now
    await conversation.save()
    logger.info("WhatsApp welcome sent | wa_id=%s | conversation_id=%s", wa_id, conversation.id)
    return True


async def _history_messages(conversation_id: int, limit: int) -> list[dict[str, Any]]:
    rows = await WaMessage.filter(conversation_id=conversation_id).order_by("-id").limit(limit * 2)
    rows = list(reversed(rows))
    history: list[dict[str, Any]] = []
    for row in rows:
        # Outbound welcome cards are UI-only; keep LLM context focused on Q&A.
        if row.direction == "out" and row.msg_type == "interactive":
            continue
        role = "user" if row.direction == "in" else "assistant"
        if row.msg_type == "image":
            caption = (row.text or "").strip()
            content = "[customer sent a photo]"
            if caption:
                content = f"{content} caption: {caption}"
            history.append({"role": role, "content": content})
            continue
        text = (row.text or "").strip()
        if not text:
            continue
        history.append({"role": role, "content": text})
    if len(history) > limit:
        history = history[-limit:]
    return history


async def _send_and_store_outbound(
    *,
    conversation: WaConversation,
    wa_id: str,
    text: str,
    tool_calls: list[dict[str, Any]] | None = None,
    token_usage: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    error_message: str | None = None,
    client: WhatsAppCloudClient | None = None,
    recognition_session_id: int | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> WaMessage:
    client = client or WhatsAppCloudClient()
    message_ids: list[str] = []
    send_error = error_message
    try:
        if client.configured:
            message_ids = client.send_text(wa_id, text)
        else:
            logger.warning("WhatsApp client not configured; storing outbound without send")
            send_error = send_error or "whatsapp_not_configured"
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp send failed | wa_id=%s", wa_id)
        send_error = str(exc)[:500]

    primary_id = message_ids[0] if message_ids else None
    # Avoid unique collisions when send fails (null id is fine).
    outbound = await WaMessage.create(
        conversation_id=conversation.id,
        direction="out",
        wa_message_id=primary_id,
        msg_type="text",
        text=text,
        raw_payload=raw_payload,
        tool_calls=tool_calls,
        delivery_status="sent" if primary_id else "failed",
        latency_ms=latency_ms,
        token_usage=token_usage,
        error_message=send_error,
        recognition_session_id=recognition_session_id,
    )
    conversation.message_count = int(conversation.message_count or 0) + 1
    conversation.last_message_at = datetime.utcnow()
    if token_usage and token_usage.get("total_tokens"):
        conversation.llm_tokens = int(conversation.llm_tokens or 0) + int(
            token_usage["total_tokens"]
        )
    await conversation.save()
    return outbound


def _button_inbound_text(button_id: str, title: str) -> str:
    label = (title or "").strip() or (button_id or "").strip() or "button"
    return f"[button] {label}"


async def handle_inbound_message(
    *,
    wa_id: str,
    profile_name: str,
    wa_message_id: str,
    msg_type: str,
    text: str,
    media_id: str = "",
    mime_type: str = "",
    caption: str = "",
    button_id: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> None:
    normalized_type = (msg_type or "text").strip().lower()

    if normalized_type == "image":
        from app.services.whatsapp_vision import ingest_image_message

        await ingest_image_message(
            wa_id=wa_id,
            profile_name=profile_name,
            wa_message_id=wa_message_id,
            media_id=media_id or "",
            mime_type=mime_type or "",
            caption=caption or text or "",
            raw_payload=raw_payload,
        )
        return

    contact = await get_or_create_contact(wa_id, profile_name)
    conversation, is_new = await get_or_create_conversation(contact)

    inbound_text = text or None
    resolved_button_id = (button_id or "").strip()
    if normalized_type == "interactive":
        title = (text or "").strip()
        if not resolved_button_id and isinstance(raw_payload, dict):
            interactive = raw_payload.get("interactive") or {}
            if isinstance(interactive, dict):
                reply = interactive.get("button_reply") or {}
                if isinstance(reply, dict):
                    resolved_button_id = str(reply.get("id") or "").strip()
                    title = title or str(reply.get("title") or "").strip()
        inbound_text = _button_inbound_text(resolved_button_id, title)

    inbound = await store_inbound_message(
        conversation=conversation,
        wa_message_id=wa_message_id,
        msg_type=normalized_type,
        text=inbound_text,
        raw_payload=raw_payload,
    )

    client = WhatsAppCloudClient()
    try:
        if client.configured:
            client.mark_read(wa_message_id, typing=True)
    except Exception:  # noqa: BLE001
        logger.warning("mark_read failed | message_id=%s", wa_message_id, exc_info=True)

    await maybe_send_welcome(conversation, wa_id, is_new=is_new, client=client)

    # Rate limit per WhatsApp user
    try:
        get_redis().check_rate_limit(
            f"wa:rl:{wa_id}",
            settings.WHATSAPP_RATE_LIMIT_PER_MINUTE,
            window_seconds=60,
        )
    except RateLimitError:
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=WHATSAPP_RATE_LIMIT_REPLY,
            client=client,
        )
        return
    except Exception:  # noqa: BLE001
        logger.warning("WhatsApp rate limit check failed (fail-open)", exc_info=True)

    if normalized_type == "interactive":
        guide = WHATSAPP_GUIDE_REPLIES.get(resolved_button_id) or (
            "Please send a part photo, type an OE/part number, "
            "or tell me the vehicle brand, model, and year."
        )
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=guide,
            client=client,
        )
        logger.info(
            "WhatsApp guide button | wa_id=%s | button_id=%s | inbound_id=%s",
            wa_id,
            resolved_button_id,
            inbound.id,
        )
        return

    if normalized_type != "text" or not (text or "").strip():
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=WHATSAPP_UNSUPPORTED_MEDIA_REPLY,
            client=client,
        )
        return

    try:
        system_prompt = await get_active_whatsapp_prompt()
        history = await _history_messages(
            conversation.id,
            max(1, int(settings.WHATSAPP_CONTEXT_MESSAGES or 20)),
        )
        # history already includes the just-stored inbound; keep as-is
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}, *history]
        chat = DeepSeekChatClient()

        async def _tool(name: str, arguments: dict[str, Any]) -> Any:
            return await dispatch_tool(name, arguments)

        reply, tool_trace, usage, latency_ms = await chat.chat_with_tools_async(
            messages,
            TOOL_DEFINITIONS,
            _tool,
        )
        if not reply.strip():
            reply = WHATSAPP_ERROR_FALLBACK_REPLY
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=reply,
            tool_calls=tool_trace or None,
            token_usage=usage,
            latency_ms=latency_ms,
            client=client,
        )
        logger.info(
            "WhatsApp handled | wa_id=%s | inbound_id=%s | tools=%s | latency_ms=%s",
            wa_id,
            inbound.id,
            len(tool_trace or []),
            latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("WhatsApp LLM handling failed | wa_id=%s", wa_id)
        await _send_and_store_outbound(
            conversation=conversation,
            wa_id=wa_id,
            text=WHATSAPP_ERROR_FALLBACK_REPLY,
            error_message=str(exc)[:500],
            client=client,
        )
