"""Shared by unit and integration tests."""
import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _no_usage_counting(monkeypatch):
    """The API-request and download counters write to Redis; tests never should, unless a test turns
    them back on with its own Redis client (tests/integration/test_platform_admin.py)."""
    monkeypatch.setattr(get_settings(), "usage_counting_enabled", False)


@pytest.fixture(autouse=True)
def _billing_enforcement_default(monkeypatch):
    """Owner rule after r8.1: billing, subscription and Abliner tests run with enforcement both OFF and ON.
    NOVA_TEST_BILLING_ENFORCEMENT=on|off sets the default for a whole run (unset: the app default, off).
    A test that sets enforcement itself still wins, because its monkeypatch runs after this fixture."""
    import os

    value = os.environ.get("NOVA_TEST_BILLING_ENFORCEMENT", "").strip().lower()
    if value in {"on", "off"}:
        monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", value == "on")
