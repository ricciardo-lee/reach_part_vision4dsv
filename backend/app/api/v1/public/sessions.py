from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

from app.core.config import settings
from app.core.exceptions import AppError
from app.models import AuditLog, DeviceSession
from app.schemas import APIResponse, DeviceSessionCreate, DeviceSessionOut
from app.services.bootstrap import new_token

logger = logging.getLogger("app.api.sessions")

router = APIRouter(prefix="/sessions", tags=["public-sessions"])


@router.post("/device", response_model=APIResponse)
async def create_device_session(payload: DeviceSessionCreate, request: Request) -> APIResponse:
    if not settings.ALLOW_ANONYMOUS_DEVICE_SESSION:
        raise AppError(
            "设备会话接口已停用，请使用账号登录",
            code="gone",
            status_code=410,
            message_key="auth.device_disabled",
        )

    token = new_token()
    expires_at = datetime.utcnow() + timedelta(hours=settings.DEVICE_SESSION_TTL_HOURS)
    session = await DeviceSession.create(
        session_token=token,
        device_id=payload.device_id,
        user_agent=request.headers.get("user-agent", "")[:512],
        ip_address=request.client.host if request.client else "",
        expires_at=expires_at,
        is_active=True,
    )
    await AuditLog.create(
        actor_type="device",
        actor_id=session.device_id,
        action="device_session.create",
        resource_type="device_session",
        resource_id=str(session.id),
        ip_address=session.ip_address,
    )
    logger.info(
        "Device session created | device_id=%s | session_id=%s | ip=%s",
        session.device_id,
        session.id,
        session.ip_address,
    )
    return APIResponse(
        data=DeviceSessionOut(session_token=session.session_token, expires_at=session.expires_at)
    )
