"""Fixed-window request limits shared by API workers through Redis."""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Callable

logger = logging.getLogger(__name__)


class FixedWindowRateLimiter:
    """Counts hits per key in fixed windows; `increment(key, ttl)` returns the new count."""

    def __init__(self, increment: Callable[[str, int], int], window_seconds: int = 60):
        self._increment = increment
        self.window_seconds = window_seconds

    def allow(self, key: str, limit: int) -> bool:
        window = int(time.time() // self.window_seconds)
        try:
            return self._increment(f"{key}:{window}", self.window_seconds) <= limit
        except Exception:  # noqa: BLE001 - a limiter outage must not take the API down
            logger.warning("Rate limiter backend unavailable; request allowed", exc_info=True)
            return True


def redis_increment(url: str) -> Callable[[str, int], int]:
    import redis

    client = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)

    def increment(key: str, ttl: int) -> int:
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, ttl)
        return count
    return increment


@lru_cache(maxsize=1)
def get_preflight_limiter() -> FixedWindowRateLimiter:
    from app.core.config import get_settings
    return FixedWindowRateLimiter(redis_increment(get_settings().redis_url))
