from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_app_user
from app.core.exceptions import UnauthorizedError
from app.core.rate_limit import enforce_login_rate_limit
from app.core.security import create_app_user_token, verify_password
from app.models import AppUser, AuditLog
from app.schemas import APIResponse, AppLoginIn, AppTokenOut

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


@router.get("/me", response_model=APIResponse)
async def me(user: AppUser = Depends(get_current_app_user)) -> APIResponse:
    return APIResponse(
        data={
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
        }
    )
