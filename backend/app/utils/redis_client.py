from __future__ import annotations

import logging
from typing import Optional

import redis

from app.core.config import settings
from app.core.exceptions import RateLimitError

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:  # noqa: BLE001
            return False

    def check_rate_limit(self, key: str, limit: int, window_seconds: int = 60) -> None:
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        count, _ = pipe.execute()
        if int(count) > limit:
            raise RateLimitError()

    def get(self, key: str) -> Optional[str]:
        return self.client.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.client.setex(key, ttl, value)

    def setnx_ex(self, key: str, ttl: int, value: str = "1") -> bool:
        """Set key only if absent, with TTL. Returns True when this call acquired the key."""
        try:
            return bool(self.client.set(key, value, nx=True, ex=ttl))
        except Exception:  # noqa: BLE001
            logger.warning("Redis setnx_ex failed | key=%s", key, exc_info=True)
            return True

    def delete(self, key: str) -> None:
        try:
            self.client.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("Redis delete failed | key=%s", key, exc_info=True)


_redis: Optional[RedisClient] = None


def get_redis() -> RedisClient:
    global _redis
    if _redis is None:
        _redis = RedisClient()
    return _redis
