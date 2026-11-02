from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_app_user
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.rate_limit import enforce_login_rate_limit
from app.core.security import create_app_user_token, verify_password
from app.models import AppUser, AuditLog, RecognitionSession
from app.schemas import APIResponse, AppLoginIn, AppTokenOut, WaOpenIn
from app.services.whatsapp_vision import get_shared_app_user

logger = logging.getLogger("app.api.public.auth")

router = APIRouter(prefix="/auth", tags=["public-auth"])


@router.post("/login", response_model=APIResponse)
async def login(payload: AppLoginIn, request: Request) -> APIResponse:
    username = payload.username.strip()
    enforce_login_rate_limit(request, username)
    user = await AppUser.get_or_none(username=username, is_active=True)
    if not user or not verify_password(payload.password, user.password_hash):
        logger.warning("App user login failed | username=%s", username)
        raise UnauthorizedError("用户名或密码错误", message_key="auth.bad_credentials")
    user.last_login_at = datetime.utcnow()
    await user.save()
    ip_address = request.client.host if request.client else ""
    await AuditLog.create(
        actor_type="app_user",
        actor_id=str(user.id),
        action="app_user.login",
        resource_type="app_user",
        resource_id=str(user.id),
        ip_address=ip_address or None,
    )
    logger.info("App user login success | username=%s", user.username)
    return APIResponse(
        data=AppTokenOut(
            access_token=create_app_user_token(str(user.id)),
            username=user.username,
            display_name=user.display_name or user.username,
        )
    )


@router.post("/wa-open", response_model=APIResponse)
async def wa_open(payload: WaOpenIn, request: Request) -> APIResponse:
    """Issue the shared WhatsApp AppUser token for a recognition session.

    H5 deep links only need ``?sid=``; no password / JWT in the URL.
    """
    public_id = (payload.public_id or "").strip()
    enforce_login_rate_limit(request, f"wa-open:{public_id or 'missing'}")
    shared = await get_shared_app_user()
    if shared is None:
        raise UnauthorizedError("WhatsApp shared account is not configured", message_key="auth.login_required")

    session = await RecognitionSession.get_or_none(public_id=public_id)
    if session is None:
        raise NotFoundError("识别会话不存在", message_key="session.not_found")

    # Claim orphan WhatsApp sessions created before shared-user ownership was added.
    if session.app_user_id is None:
        session.app_user_id = shared.id
        await session.save()
    elif int(session.app_user_id) != int(shared.id):
        raise ForbiddenError("无权访问该识别会话", message_key="session.forbidden")

    shared.last_login_at = datetime.utcnow()
    await shared.save()
    ip_address = request.client.host if request.client else ""
    await AuditLog.create(
        actor_type="app_user",
        actor_id=str(shared.id),
        action="app_user.wa_open",
        resource_type="recognition_session",
        resource_id=str(session.id),
        ip_address=ip_address or None,
    )
    logger.info(
        "WhatsApp H5 open | public_id=%s | app_user_id=%s",
        session.public_id,
        shared.id,
    )
    return APIResponse(
        data=AppTokenOut(
            access_token=create_app_user_token(str(shared.id)),
            username=shared.username,
            display_name=shared.display_name or shared.username,
        )
    )


@router.get("/me", response_model=APIResponse)
async def me(user: AppUser = Depends(get_current_app_user)) -> APIResponse:
    return APIResponse(
        data={
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
        }
    )
