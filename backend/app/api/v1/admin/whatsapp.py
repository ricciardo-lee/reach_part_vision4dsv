"""Admin APIs for WhatsApp conversations and stats."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from tortoise.functions import Avg, Sum

from app.api.deps import require_permission
from app.core.exceptions import NotFoundError
from app.models import AdminUser, RecognitionSession, WaContact, WaConversation, WaMessage
from app.schemas import APIResponse

router = APIRouter(prefix="/whatsapp", tags=["admin-whatsapp"])


@router.get("/stats", response_model=APIResponse)
async def whatsapp_stats(
    admin: AdminUser = Depends(require_permission("whatsapp:read")),
) -> APIResponse:
    conversations = await WaConversation.all().count()
    open_conversations = await WaConversation.filter(status="open").count()
    messages = await WaMessage.all().count()
    inbound = await WaMessage.filter(direction="in").count()
    outbound = await WaMessage.filter(direction="out").count()
    contacts = await WaContact.all().count()

    token_row = await WaConversation.all().annotate(total=Sum("llm_tokens")).values("total")
    total_tokens = int((token_row[0].get("total") if token_row else 0) or 0)

    latency_row = (
        await WaMessage.filter(direction="out", latency_ms__not_isnull=True)
        .annotate(avg_latency=Avg("latency_ms"))
        .values("avg_latency")
    )
    avg_latency = latency_row[0].get("avg_latency") if latency_row else None
    if avg_latency is not None:
        avg_latency = round(float(avg_latency), 1)

    return APIResponse(
        data={
            "contacts": contacts,
            "conversations": conversations,
            "open_conversations": open_conversations,
            "messages": messages,
            "inbound_messages": inbound,
            "outbound_messages": outbound,
            "llm_tokens": total_tokens,
            "avg_outbound_latency_ms": avg_latency,
        }
    )


@router.get("/conversations", response_model=APIResponse)
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    wa_id: Optional[str] = None,
    admin: AdminUser = Depends(require_permission("whatsapp:read")),
) -> APIResponse:
    query = WaConversation.all().prefetch_related("contact")
    if status:
        query = query.filter(status=status)
    if wa_id:
        query = query.filter(contact__wa_id__contains=wa_id.strip())

    total = await query.count()
    rows = (
        await query.order_by("-last_message_at", "-id")
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for row in rows:
        contact = row.contact
        items.append(
            {
                "id": row.id,
                "status": row.status,
                "message_count": row.message_count,
                "llm_tokens": row.llm_tokens,
                "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "wa_id": contact.wa_id if contact else None,
                "profile_name": contact.profile_name if contact else None,
            }
        )
    return APIResponse(data={"total": total, "page": page, "page_size": page_size, "items": items})


@router.get("/conversations/{conversation_id}/messages", response_model=APIResponse)
async def list_messages(
    conversation_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: AdminUser = Depends(require_permission("whatsapp:read")),
) -> APIResponse:
    conversation = await WaConversation.get_or_none(id=conversation_id).prefetch_related("contact")
    if conversation is None:
        raise NotFoundError("Conversation not found")

    query = WaMessage.filter(conversation_id=conversation_id)
    total = await query.count()
    rows = await query.order_by("id").offset((page - 1) * page_size).limit(page_size)
    session_ids = {
        int(row.recognition_session_id)
        for row in rows
        if row.recognition_session_id
    }
    public_id_by_session: dict[int, str] = {}
    if session_ids:
        sessions = await RecognitionSession.filter(id__in=list(session_ids)).all()
        public_id_by_session = {s.id: s.public_id for s in sessions}
    items = [
        {
            "id": row.id,
            "direction": row.direction,
            "wa_message_id": row.wa_message_id,
            "msg_type": row.msg_type,
            "text": row.text,
            "tool_calls": row.tool_calls,
            "delivery_status": row.delivery_status,
            "latency_ms": row.latency_ms,
            "token_usage": row.token_usage,
            "error_message": row.error_message,
            "recognition_session_id": row.recognition_session_id,
            "recognition_session_public_id": public_id_by_session.get(row.recognition_session_id)
            if row.recognition_session_id
            else None,
            "media_id": row.media_id,
            "object_key": row.object_key,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
    contact = conversation.contact
    return APIResponse(
        data={
            "conversation": {
                "id": conversation.id,
                "status": conversation.status,
                "message_count": conversation.message_count,
                "llm_tokens": conversation.llm_tokens,
                "wa_id": contact.wa_id if contact else None,
                "profile_name": contact.profile_name if contact else None,
            },
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
    )
