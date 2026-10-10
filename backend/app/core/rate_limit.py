"""Shared rate-limit helpers for auth and other public endpoints."""

from __future__ import annotations

import logging
import re

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.utils.redis_client import get_redis

logger = logging.getLogger("app.rate_limit")

_USERNAME_SAFE = re.compile(r"[^a-zA-Z0-9_.\-@]+")


def client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return "unknown"


def _safe_username(username: str) -> str:
    text = (username or "").strip().lower()[:64] or "-"
    return _USERNAME_SAFE.sub("_", text)


def enforce_login_rate_limit(request: Request, username: str) -> None:
    """Limit login attempts by IP and username. Redis outages fail open."""
    ip = client_ip(request)
    user_key = _safe_username(username)
    try:
        redis = get_redis()
        redis.check_rate_limit(
            f"rate:login:ip:{ip}",
            settings.LOGIN_RATE_LIMIT_PER_MINUTE_IP,
        )
        redis.check_rate_limit(
            f"rate:login:user:{user_key}",
            settings.LOGIN_RATE_LIMIT_PER_MINUTE_USER,
        )
    except RateLimitError:
        logger.warning("Login rate limited | ip=%s | username=%s", ip, user_key)
        raise RateLimitError("登录过于频繁，请稍后再试", message_key="auth.rate_limited")
    except Exception:  # noqa: BLE001
        logger.warning("Login rate limit skipped | ip=%s | username=%s", ip, user_key)
