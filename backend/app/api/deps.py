from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import ForbiddenError, NotFoundError, RateLimitError, UnauthorizedError
from app.core.security import decode_token, has_permission
from app.models import AdminUser, DeviceSession, RecognitionSession
from app.utils.redis_client import get_redis
from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


async def get_device_session(
    request: Request,
    x_device_token: Optional[str] = Header(default=None, alias="X-Device-Token"),
) -> DeviceSession:
    if not x_device_token:
        raise UnauthorizedError("缺少设备会话 Token")
    session = await DeviceSession.get_or_none(session_token=x_device_token, is_active=True)
    if not session or session.expires_at < datetime.utcnow():
        raise UnauthorizedError("设备会话无效或已过期")
    try:
        get_redis().check_rate_limit(
            f"rate:device:{session.device_id}",
            settings.RATE_LIMIT_PER_MINUTE,
        )
    except RateLimitError:
        raise
    except Exception:
        # Redis 不可用时跳过限流，避免阻断主流程（fail-open）
        pass
    request.state.device_session = session
    return session


async def get_recognition_session(
    public_id: str,
    device_session: DeviceSession = Depends(get_device_session),
) -> RecognitionSession:
    session = await RecognitionSession.get_or_none(public_id=public_id)
    if not session:
        raise NotFoundError("识别会话不存在")
    if session.device_session_id and session.device_session_id != device_session.id:
        raise ForbiddenError("无权访问该识别会话")
    return session


async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AdminUser:
    if not credentials:
        raise UnauthorizedError()
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise UnauthorizedError("Token 无效") from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Token 类型错误")
    user = await AdminUser.get_or_none(id=int(payload["sub"]), is_active=True)
    if not user:
        raise UnauthorizedError("管理员不存在或已禁用")
    return user


def require_permission(permission: str):
    async def _dependency(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
        if not has_permission(admin.role, permission):
            raise ForbiddenError(f"缺少权限: {permission}")
        return admin

    return _dependency
