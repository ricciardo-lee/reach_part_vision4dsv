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


_redis: Optional[RedisClient] = None


def get_redis() -> RedisClient:
    global _redis
    if _redis is None:
        _redis = RedisClient()
    return _redis
