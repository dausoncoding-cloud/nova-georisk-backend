"""Fixed-window limiter used by the FIRRIS preflight endpoint."""
from app.core.rate_limit import FixedWindowRateLimiter


def test_limit_applies_per_key_within_a_window(monkeypatch):
    counts = {}
    limiter = FixedWindowRateLimiter(lambda key, ttl: counts.__setitem__(key, counts.get(key, 0) + 1) or counts[key])
    monkeypatch.setattr("app.core.rate_limit.time.time", lambda: 1_000.0)
    assert [limiter.allow("user:a", 2) for _ in range(3)] == [True, True, False]
    assert limiter.allow("user:b", 2) is True
    monkeypatch.setattr("app.core.rate_limit.time.time", lambda: 1_060.0)  # next window
    assert limiter.allow("user:a", 2) is True


def test_backend_outage_does_not_block_requests():
    def broken(key, ttl):
        raise ConnectionError("redis down")
    assert FixedWindowRateLimiter(broken).allow("user:a", 1) is True
