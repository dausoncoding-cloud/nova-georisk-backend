"""The BFF webhook rate limit against a real Redis (production edge -> BFF directly, review row B2)."""
import asyncio
import os
import uuid

import pytest

from app.bff.webhook_limit import PER_SOURCE, TOTAL, WebhookLimiter

REDIS_URL = os.environ.get("SESSIONS_TEST_REDIS_URL") or os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture()
def limiter():
    import redis
    import redis.asyncio as redis_asyncio

    probe = redis.Redis.from_url(REDIS_URL, db=7, socket_connect_timeout=1)
    try:
        probe.ping()
    except Exception:
        pytest.skip(f"No Redis at {REDIS_URL}")
    client = redis_asyncio.Redis.from_url(REDIS_URL, db=7, decode_responses=True)
    instance = WebhookLimiter(client=client, clock=lambda: 1_790_000_000)
    instance._prefix = f"nova:test:{uuid.uuid4().hex[:8]}:webhook-rl:"
    yield instance
    for key in probe.scan_iter(f"{instance._prefix}*"):
        probe.delete(key)


def test_per_source_and_total_limits(limiter):
    async def run():
        first = [await limiter.allow("41.59.10.20") for _ in range(PER_SOURCE + 1)]
        other = await limiter.allow("41.59.10.21")  # another source still passes
        return first, other

    first, other = asyncio.run(run())
    assert first[:PER_SOURCE] == [True] * PER_SOURCE and first[-1] is False and other is True
    assert TOTAL > PER_SOURCE


def test_fails_open_without_redis():
    import redis.asyncio as redis_asyncio

    dead = redis_asyncio.Redis.from_url("redis://127.0.0.1:9/0", socket_connect_timeout=0.2, socket_timeout=0.2)
    assert asyncio.run(WebhookLimiter(client=dead).allow("1.2.3.4")) is True
