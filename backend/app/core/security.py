from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.constants import PERMISSIONS

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_token(subject: str, token_type: str, expires_delta: timedelta, extra: Optional[dict] = None) -> str:
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "exp": datetime.utcnow() + expires_delta,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str, extra: Optional[dict] = None) -> str:
    return create_token(
        subject,
        "access",
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        extra,
    )


def create_refresh_token(subject: str, extra: Optional[dict] = None) -> str:
    return create_token(
        subject,
        "refresh",
        timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        extra,
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc


def role_permissions(role: str) -> set[str]:
    return set(PERMISSIONS.get(role, set()))


def has_permission(role: str, permission: str) -> bool:
    return permission in role_permissions(role)
