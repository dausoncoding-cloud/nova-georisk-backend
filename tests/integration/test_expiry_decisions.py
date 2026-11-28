"""Q7 (decided 2026-11-21): on expiry new analyses stop; viewing and downloads stay for 2 days, then close.
"Renew plan" (Mobile Money too) brings everything back; top-up credits are usable only with an active plan.
Also the seller identity on My subscription (Q6)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.models.platform import SubscriptionStatus
from app.services.billing import audit, payments, statuses
from tests.integration.test_billing_accounts import _submit
from tests.integration.test_billing_credits import _queue, _tenant  # noqa: F401 (_queue: no Celery)

SYSTEM = audit.Actor(user_id=None, label="system:abliner")


@pytest.fixture(autouse=True, params=[False, True], ids=["enforcement-off", "enforcement-on"])
def enforcement(request, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", request.param)
    return request.param


def test_expiry_grace_of_two_days_then_renewal_brings_everything_back(client, db_session, enforcement, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_view_grace_days", 2)  # the Phase B server setting (H1)
    t = _tenant(db_session, "exp-renew", credits=5)
    task_path = f"/api/v1/tasks/{_submit(client, t).json()['task']['id']}"
    t.sub.ends_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    statuses.sweep(db_session, apply=True, actor=audit.Actor.command("sweep-statuses"))
    db_session.commit()
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]
    assert summary["status"] == "expired"
    if enforcement:
        ends = datetime.fromisoformat(summary["access_ends_at"])
        assert timedelta(days=1, hours=23) < ends - datetime.now(timezone.utc) <= timedelta(days=2)
    else:
        assert summary["access_ends_at"] is None  # H1: with enforcement off viewing never closes
    blocked = _submit(client, t)
    assert blocked.status_code == (402 if enforcement else 202)
    if enforcement:
        assert blocked.json()["error"]["code"] == "subscription_expired"
    assert client.get(task_path, headers=t.headers).status_code == 200  # inside the 2 days
    # Top-ups need an active plan; renewal is on offer.
    refused = client.post("/api/v1/billing/requests", headers=t.headers,
                          json={"subscription_id": str(t.sub.id), "kind": "top_up"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "plan_not_active"
    offers = {item["purpose"]: item for item in client.get(
        f"/api/v1/billing/abliner/offers?subscription_id={t.sub.id}", headers=t.headers).json()["offers"]}
    assert offers["renewal"]["available"] is True and offers["top_up"]["unavailable_code"] == "plan_not_active"
    # After the 2 days the sweep closes viewing and downloads.
    t.sub.status_changed_at = datetime.now(timezone.utc) - timedelta(days=2, minutes=1)
    db_session.commit()
    closed = statuses.sweep(db_session, apply=True, actor=audit.Actor.command("sweep-statuses"))
    db_session.commit()
    if not enforcement:  # H1: nothing closes while enforcement is off, even with the grace set
        assert closed == [] and client.get(task_path, headers=t.headers).status_code == 200
        return
    assert [item["action"] for item in closed] == ["close_entitlements"]
    assert client.get(task_path, headers=t.headers).status_code == 403
    # "Renew plan": the plan payment (manual or Abliner-settled, same service) reactivates and reopens.
    today = date.today()
    payments.record_plan_payment(db_session, t.sub.id, amount=150_000, method="mobile_money", paid_on=today,
                                 covers_from=today, covers_until=today + timedelta(days=30), actor=SYSTEM,
                                 key="abliner:renewal-test", reference="NOVA-RENEW1")
    db_session.commit()
    db_session.refresh(t.sub)
    assert t.sub.status == SubscriptionStatus.ACTIVE
    assert client.get(task_path, headers=t.headers).status_code == 200
    assert client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]["access_ends_at"] is None
    assert _submit(client, t).status_code == 202


def test_seller_identity_comes_from_settings(client, db_session, monkeypatch):
    t = _tenant(db_session, "exp-seller")
    assert client.get("/api/v1/billing/summary", headers=t.headers).json()["seller"] is None
    settings = get_settings()
    monkeypatch.setattr(settings, "seller_legal_name", "Seller Placeholder Ltd")
    monkeypatch.setattr(settings, "seller_tin", "100-000-000")
    monkeypatch.setattr(settings, "seller_vat_mode", "inclusive")
    seller = client.get("/api/v1/billing/summary", headers=t.headers).json()["seller"]
    assert seller == {"legal_name": "Seller Placeholder Ltd", "tin": "100-000-000", "address": None,
                      "vat_mode": "inclusive", "vat_rate_percent": 18}


# --- Security review H1 -------------------------------------------------------------------------------------------

def test_h1_the_grace_is_unset_by_default():
    assert type(get_settings()).model_fields["billing_view_grace_days"].default is None
    assert statuses.grace_days_in_force() is None


@pytest.mark.parametrize("grace", [None, 2], ids=["grace-unset", "grace-set"])
@pytest.mark.parametrize("ended", ["expired", "canceled"])
def test_h1_with_enforcement_off_the_sweep_never_closes_viewing_or_downloads(client, db_session, monkeypatch, grace, ended):
    """Expired and cancelled subscriptions older than 2 days keep viewing and downloads while billing enforcement
    is off, whatever BILLING_VIEW_GRACE_DAYS says."""
    from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement

    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", False)
    monkeypatch.setattr(get_settings(), "billing_view_grace_days", grace)
    t = _tenant(db_session, f"h1-{ended}-{grace}", credits=3)
    task_path = f"/api/v1/tasks/{_submit(client, t).json()['task']['id']}"
    statuses.change_status(db_session, t.sub.id, ended, reason="Ended", actor=SYSTEM)
    t.sub.status_changed_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.commit()
    for apply in (False, True):
        actions = statuses.sweep(db_session, apply=apply, actor=audit.Actor.command("sweep-statuses"))
        db_session.commit()
        assert [a for a in actions if a["action"] == "close_entitlements"] == []
    entitlement = db_session.query(OrganizationEngineEntitlement).filter_by(organization_id=t.org.id).one()
    db_session.refresh(entitlement)
    assert entitlement.status == EntitlementStatus.ACTIVE  # downloads are gated by this entitlement
    assert client.get(task_path, headers=t.headers).status_code == 200
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]
    assert summary["access_ends_at"] is None

