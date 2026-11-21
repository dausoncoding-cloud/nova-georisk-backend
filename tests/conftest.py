"""Shared by unit and integration tests."""
import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _no_usage_counting(monkeypatch):
    """The API-request and download counters write to Redis; tests never should, unless a test turns
    them back on with its own Redis client (tests/integration/test_platform_admin.py)."""
    monkeypatch.setattr(get_settings(), "usage_counting_enabled", False)
