"""Rate limit for the BFF's Abliner webhook route (review row B2).

In production the app-host edge sends /api/* straight to the BFF (r8 nginx audit), so the gateway location's
rate limit is not on the path. The BFF therefore limits by itself, per source IP (the client address behind
our trusted proxies, as for sessions) and in total, in fixed 10-second windows counted in Redis:
- per source: 30 requests / 10 s (Abliner sends one event plus at most two retries per transaction);
- all sources: 300 requests / 10 s.
If Redis is unavailable the limit fails open and logs a warning: the request still has to pass the internal
secret and the HMAC check in the API.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 10
PER_SOURCE = 30
TOTAL = 300


class WebhookLimiter:
    def __init__(self, client=None, clock=time.time):
        self._client = client
        self._clock = clock
        settings = get_settings()
        self._prefix = settings.session_redis_prefix.split(":")[0] + ":bff:webhook-rl:"

    def _redis(self):
        if self._client is None:
            import redis.asyncio as redis_asyncio

            self._client = redis_asyncio.Redis.from_url(get_settings().redis_url, decode_responses=True,
                                                        socket_connect_timeout=0.2, socket_timeout=0.2)
        return self._client

    async def allow(self, source: str) -> bool:
        window = int(self._clock() // WINDOW_SECONDS)
        source_key = f"{self._prefix}{source}:{window}"
        total_key = f"{self._prefix}all:{window}"
        try:
            pipe = self._redis().pipeline()
            pipe.incr(source_key)
            pipe.expire(source_key, WINDOW_SECONDS * 2)
            pipe.incr(total_key)
            pipe.expire(total_key, WINDOW_SECONDS * 2)
            per_source, _, total, _ = await pipe.execute()
        except Exception:
            logger.warning("Webhook rate limit unavailable; allowing the request")
            return True
        return int(per_source) <= PER_SOURCE and int(total) <= TOTAL


@lru_cache
def get_webhook_limiter() -> WebhookLimiter:
    return WebhookLimiter()
