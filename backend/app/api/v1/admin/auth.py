from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_admin
from app.core.exceptions import UnauthorizedError
from app.core.rate_limit import enforce_login_rate_limit
from app.core.security import create_access_token, create_refresh_token, verify_password
from app.models import AdminUser, AuditLog
from app.schemas import APIResponse, AdminLoginIn, TokenOut

logger = logging.getLogger("app.api.admin.auth")

router = APIRouter(prefix="/auth", tags=["admin-auth"])


@router.post("/login", response_model=APIResponse)
async def login(payload: AdminLoginIn, request: Request) -> APIResponse:
    enforce_login_rate_limit(request, payload.username)
    user = await AdminUser.get_or_none(username=payload.username, is_active=True)
    if not user or not verify_password(payload.password, user.password_hash):
        logger.warning("Admin login failed | username=%s", payload.username)
        raise UnauthorizedError("用户名或密码错误", message_key="auth.bad_credentials")
    user.last_login_at = datetime.utcnow()
    await user.save()
    await AuditLog.create(
        actor_type="admin",
        actor_id=str(user.id),
        action="admin.login",
        resource_type="admin_user",
        resource_id=str(user.id),
    )
    logger.info("Admin login success | username=%s | role=%s", user.username, user.role)
    return APIResponse(
        data=TokenOut(
            access_token=create_access_token(str(user.id), {"role": user.role}),
            refresh_token=create_refresh_token(str(user.id), {"role": user.role}),
            role=user.role,
            display_name=user.display_name or user.username,
        )
    )


@router.get("/me", response_model=APIResponse)
async def me(admin: AdminUser = Depends(get_current_admin)) -> APIResponse:
    return APIResponse(
        data={
            "id": admin.id,
            "username": admin.username,
            "display_name": admin.display_name,
            "role": admin.role,
        }
    )
