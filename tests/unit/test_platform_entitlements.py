from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.entitlements import entitlement_is_active
from app.models.platform import EntitlementStatus
from app.platform.registry import ENGINE_DEFINITIONS, ENGINE_KEYS


def _entitlement(status, **kwargs):
    return SimpleNamespace(
        status=status,
        starts_at=kwargs.get("starts_at"),
        ends_at=kwargs.get("ends_at"),
        trial_ends_at=kwargs.get("trial_ends_at"),
    )


def test_engine_registry_has_stable_keys_and_shared_execution_namespace():
    assert ENGINE_KEYS == {
        "firris", "wras", "lucas", "hasas", "veras",
        "diras", "lstas", "wqras", "lras", "megis",
    }
    assert {item.route_namespace for item in ENGINE_DEFINITIONS if item.key in {"firris", "megis", "wras"}} == {
        "/api/v1/analyses"
    }
    firris = next(item for item in ENGINE_DEFINITIONS if item.key == "firris")
    assert firris.enabled is True
    assert all(not item.enabled for item in ENGINE_DEFINITIONS if item.key != "firris")


def test_active_entitlement_is_effective_inside_window():
    now = datetime.now(timezone.utc)
    assert entitlement_is_active(
        _entitlement(
            EntitlementStatus.ACTIVE,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
        ),
        now,
    )


def test_missing_time_window_expired_and_suspended_entitlements_are_inactive():
    now = datetime.now(timezone.utc)
    assert not entitlement_is_active(
        _entitlement(EntitlementStatus.ACTIVE, starts_at=now + timedelta(minutes=1)), now
    )
    assert not entitlement_is_active(
        _entitlement(EntitlementStatus.EXPIRED, ends_at=now - timedelta(minutes=1)), now
    )
    assert not entitlement_is_active(_entitlement(EntitlementStatus.SUSPENDED), now)


def test_trial_requires_unexpired_trial_end():
    now = datetime.now(timezone.utc)
    assert entitlement_is_active(
        _entitlement(EntitlementStatus.TRIAL, trial_ends_at=now + timedelta(hours=1)), now
    )
    assert not entitlement_is_active(
        _entitlement(EntitlementStatus.TRIAL, trial_ends_at=now - timedelta(seconds=1)), now
    )
    assert not entitlement_is_active(_entitlement(EntitlementStatus.TRIAL), now)
