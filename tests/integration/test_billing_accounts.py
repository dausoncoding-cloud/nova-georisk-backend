"""Subscriptions M2: manual payments, top-ups, reversals, account statuses, seats, storage, Internal plan,
backfill before enforcement."""
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.bff.membership import MembershipResolutionError, invitation_token_hash, resolve_membership
from app.bff.oidc import OIDCClaims
from app.core.config import get_settings
from app.models.billing import CreditLedgerEntry, Payment, PlatformAudit
from app.models.identity import MembershipRole, Organization, OrganizationInvitation, OrganizationMembership, User
from app.models.management import ManagedDataset
from app.models.platform import (BillingPlan, EntitlementStatus, OrganizationEngineEntitlement, OrganizationSubscription,
                                 SubscriptionStatus)
from app.models.result import Result
from app.models.task import Task
from app.services.billing import audit, backfill, catalogue, ledger, limits, payments, statuses
from app.services.billing.cli import run_backfill
from tests.integration.test_billing_credits import _entries, _payload, _queue, _tenant, enforced  # noqa: F401

ADMIN = audit.Actor(user_id=None, label="test: NOVA ARI admin")


def _key() -> str:
    return f"test-{uuid.uuid4()}"


def _audit(db, action=None, org=None):
    query = db.query(PlatformAudit)
    if action:
        query = query.filter(PlatformAudit.action == action)
    if org:
        query = query.filter(PlatformAudit.organization_id == org.id)
    return query.order_by(PlatformAudit.created_at).all()


def _submit(client, t):
    return client.post("/api/v1/analyses", headers=t.headers, json=_payload(t))


def _exhaust(client, db, t):
    while ledger.balances(db, t.sub.id).total > 0 or not _entries(db, t.sub, "monthly_grant"):
        assert _submit(client, t).status_code == 202
    assert _submit(client, t).json()["error"]["code"] == "credits_exhausted"


# --- catalogue and Internal plan ------------------------------------------------------------------

def test_internal_plan_is_seeded_hidden_and_unpriced(client, db_session):
    report = catalogue.seed_catalogue(db_session)
    db_session.commit()
    assert {"frris_wrris.internal", "megis.internal"} <= set(report.plans) and len(report.prices) == 12
    plan = db_session.get(BillingPlan, "frris_wrris.internal")
    assert (plan.is_internal, plan.unlimited_credits, plan.seat_limit, plan.storage_bytes) == (True, True, None, None)
    assert catalogue.current_price(db_session, "frris_wrris.internal") is None
    t = _tenant(db_session, "internal-hidden")
    keys = [item["key"] for item in client.get("/api/v1/billing/plans?family=frris_wrris", headers=t.headers).json()["plans"]]
    assert "frris_wrris.internal" not in keys and len(keys) == 6


def test_internal_plan_submits_without_credits_or_charges(client, db_session, enforced):
    t = _tenant(db_session, "internal-unlimited", plan_key="frris_wrris.internal")
    for _ in range(3):
        assert _submit(client, t).status_code == 202
    assert _entries(db_session, t.sub) == []  # never granted, never charged
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()
    item = summary["subscriptions"][0]
    assert item["is_internal"] is True and item["credits"]["unlimited"] is True and item["can_submit"] is True
    assert summary["seats"]["limit"] is None and summary["storage"]["limit"] is None
    # Status rules still apply to the Internal plan.
    statuses.change_status(db_session, t.sub.id, "suspended", reason="Test suspension", actor=ADMIN)
    db_session.commit()
    assert _submit(client, t).json()["error"]["code"] == "subscription_suspended"
    with pytest.raises(payments.PaymentError) as caught:
        payments.grant_top_up(db_session, t.sub.id, credits=5, reason="No", actor=ADMIN, key=_key())
    assert caught.value.code == "credits_unlimited"


# --- payments -------------------------------------------------------------------------------------

def test_top_up_payment_adds_credits_in_the_same_transaction_and_unblocks(client, db_session, enforced):
    t = _tenant(db_session, "topup-pay", credits=1)
    _exhaust(client, db_session, t)
    key = _key()
    result = payments.record_top_up_payment(
        db_session, t.sub.id, credits=10, amount=100_000, method="mobile_money", paid_on=date.today(),
        reference="MP-123", note="Pack of 10", actor=ADMIN, key=key)
    db_session.commit()
    assert result.entry.kind == "top_up" and result.entry.amount == 10 and result.entry.bucket == "top_up"
    assert result.entry.idempotency_key == f"topup:{result.payment.id}" and result.entry.payment_id == result.payment.id
    assert result.payment.expected_amount == 150_000  # Q1: the Researcher list price
    again = payments.record_top_up_payment(
        db_session, t.sub.id, credits=10, amount=100_000, method="mobile_money", paid_on=date.today(),
        reference="MP-123", note="Pack of 10", actor=ADMIN, key=key)  # the identical request (a different one is a 409)
    assert again.replayed and again.payment.id == result.payment.id
    assert db_session.query(Payment).count() == 1 and len(_entries(db_session, t.sub, "top_up")) == 1
    assert _submit(client, t).status_code == 202
    entry = _entries(db_session, t.sub, "charge")[-1]
    assert entry.bucket == "top_up"
    assert [row.action for row in _audit(db_session, org=t.org)] == ["payment.record_top_up"]
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]
    assert summary["credits"]["top_ups"] == 10 and summary["credits"]["remaining"] == 9


def test_payment_validation(db_session):
    t = _tenant(db_session, "pay-validate")
    common = dict(actor=ADMIN, paid_on=date.today(), amount=100_000)
    cases = [
        (dict(credits=10, method="cheque"), "payment_method_invalid"),
        (dict(credits=10, method="cash", paid_on=date.today() + timedelta(days=2)), "payment_date_invalid"),
        (dict(credits=0, method="cash"), "credits_invalid"),
        (dict(credits=10, method="cash", amount=-5), "payment_amount_invalid"),
        (dict(credits=10, method="cash", currency="USD"), "payment_currency_invalid"),
    ]
    for overrides, code in cases:
        with pytest.raises(payments.PaymentError) as caught:
            payments.record_top_up_payment(db_session, t.sub.id, key=_key(), **{**common, **overrides})
        assert caught.value.code == code
    db_session.rollback()
    first = payments.record_top_up_payment(db_session, t.sub.id, credits=10, method="cash", key="same-key", **common)
    with pytest.raises(payments.PaymentError) as caught:
        payments.record_plan_payment(db_session, t.sub.id, method="cash", key="same-key", covers_from=date.today(),
                                     covers_until=date.today(), **common)
    assert caught.value.code == "request_key_reused" and first.payment is not None


def test_megis_top_up_list_price_is_25000_per_credit_q2(db_session):
    t = _tenant(db_session, "megis-topup", plan_key="megis.professional")
    t.sub.family = "megis"
    db_session.commit()
    result = payments.record_top_up_payment(db_session, t.sub.id, credits=10, amount=250_000, method="cash",
                                            paid_on=date.today(), actor=ADMIN, key=_key())
    assert result.payment.expected_amount == 250_000 and result.entry.amount == 10


def test_plan_payment_reactivates_and_extends_but_never_lifts_a_suspension(db_session):
    t = _tenant(db_session, "plan-pay", status=SubscriptionStatus.EXPIRED)
    past = datetime.now(timezone.utc) - timedelta(days=3)
    t.sub.ends_at = past
    db_session.commit()
    # "Today" on the billing calendar (Africa/Dar_es_Salaam), as payments._end_of uses: date.today() is the
    # container's UTC date, a day behind from 00:00 to 03:00 EAT, which made this fail in that window.
    today = datetime.now(ledger._zone()).date()
    payments.record_plan_payment(db_session, t.sub.id, amount=150_000, method="bank_transfer", paid_on=today,
                                 covers_from=today, covers_until=today + timedelta(days=30), reference="BT-1",
                                 actor=ADMIN, key=_key())
    db_session.commit()
    db_session.refresh(t.sub)
    assert t.sub.status == SubscriptionStatus.ACTIVE and t.sub.ends_at > datetime.now(timezone.utc) + timedelta(days=30)
    assert ledger.is_current(t.sub)
    assert [row.action for row in _audit(db_session, org=t.org)] == ["payment.record", "subscription.payment_applied"]
    statuses.change_status(db_session, t.sub.id, "suspended", reason="Unpaid invoice", actor=ADMIN)
    db_session.commit()
    payments.record_plan_payment(db_session, t.sub.id, amount=150_000, method="cash", paid_on=today,
                                 covers_from=today + timedelta(days=31), covers_until=today + timedelta(days=61),
                                 actor=ADMIN, key=_key())
    db_session.commit()
    db_session.refresh(t.sub)
    assert t.sub.status == SubscriptionStatus.SUSPENDED and t.sub.ends_at > datetime.now(timezone.utc) + timedelta(days=61)


def test_top_up_reversal_removes_unspent_credits_once(client, db_session, enforced):
    t = _tenant(db_session, "reverse", credits=0)
    paid = payments.record_top_up_payment(db_session, t.sub.id, credits=10, amount=100_000, method="cash",
                                          paid_on=date.today(), actor=ADMIN, key=_key())
    db_session.commit()
    for _ in range(3):
        assert _submit(client, t).status_code == 202
    reversal = payments.reverse_payment(db_session, paid.payment.id, reason="Payment bounced", actor=ADMIN, key=_key())
    db_session.commit()
    assert reversal.payment.amount == -100_000 and reversal.payment.purpose == "reversal"
    assert reversal.entry.kind == "adjustment" and reversal.entry.amount == -7
    assert reversal.entry.metadata_json["shortfall"] == 3
    assert ledger.balances(db_session, t.sub.id).total == 0
    with pytest.raises(payments.PaymentError) as caught:
        payments.reverse_payment(db_session, paid.payment.id, reason="Again", actor=ADMIN, key=_key())
    assert caught.value.code == "payment_already_reversed"
    with pytest.raises(payments.PaymentError) as caught:
        payments.reverse_payment(db_session, reversal.payment.id, reason="Undo", actor=ADMIN, key=_key())
    assert caught.value.code == "payment_not_reversible"
    with pytest.raises(audit.ReasonRequired):
        payments.reverse_payment(db_session, paid.payment.id, reason="  ", actor=ADMIN, key=_key())
    event = _audit(db_session, "payment.reverse")[0]
    assert event.current["credits_removed"] == 7 and event.current["credits_shortfall"] == 3


def test_grant_and_adjust_need_a_reason_and_never_go_below_zero(db_session):
    t = _tenant(db_session, "adjust", credits=2)
    with pytest.raises(audit.ReasonRequired):
        payments.grant_top_up(db_session, t.sub.id, credits=5, reason="", actor=ADMIN, key=_key())
    key = _key()
    entry = payments.grant_top_up(db_session, t.sub.id, credits=5, reason="Pilot goodwill", actor=ADMIN, key=key)
    assert payments.grant_top_up(db_session, t.sub.id, credits=5, reason="Pilot goodwill", actor=ADMIN, key=key).id == entry.id
    assert ledger.balances(db_session, t.sub.id).top_up == 5
    with pytest.raises(payments.PaymentError) as caught:
        payments.adjust_credits(db_session, t.sub.id, amount=-6, bucket="top_up", reason="Too much", actor=ADMIN, key=_key())
    assert caught.value.code == "credits_insufficient"
    payments.adjust_credits(db_session, t.sub.id, amount=-2, bucket="top_up", reason="Duplicate grant", actor=ADMIN,
                            key=_key())
    db_session.commit()
    assert ledger.balances(db_session, t.sub.id).top_up == 3
    assert [row.action for row in _audit(db_session, org=t.org)] == ["credits.grant_top_up", "credits.adjust"]


def test_payments_and_platform_audit_are_append_only(db_session):
    t = _tenant(db_session, "immutable-pay")
    payments.record_top_up_payment(db_session, t.sub.id, credits=10, amount=100_000, method="cash",
                                   paid_on=date.today(), actor=ADMIN, key=_key())
    db_session.commit()
    for statement in ("UPDATE payments SET amount = 1", "DELETE FROM payments", "UPDATE platform_audit SET reason = 'x'",
                      "DELETE FROM platform_audit", "TRUNCATE platform_audit CASCADE"):
        with pytest.raises(DBAPIError, match="append-only"):
            db_session.execute(text(statement))
        db_session.rollback()


# --- statuses ---------------------------------------------------------------------------------------

def test_suspended_and_cancelled_block_new_analyses_but_keep_viewing(client, db_session, enforced):
    t = _tenant(db_session, "status-view", credits=5)
    created = _submit(client, t)
    assert created.status_code == 202
    task_id = created.json()["task"]["id"]
    for status, code in (("suspended", "subscription_suspended"), ("canceled", "subscription_canceled")):
        statuses.change_status(db_session, t.sub.id, status, reason=f"Test {status}", actor=ADMIN)
        db_session.commit()
        refused = _submit(client, t)
        assert refused.status_code == 402 and refused.json()["error"]["code"] == code
        assert client.get(f"/api/v1/tasks/{task_id}", headers=t.headers).status_code == 200
        assert client.get(f"/api/v1/results?project_id={t.project.id}", headers=t.headers).status_code == 200
        summary = client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]
        assert summary["block_code"] == code and summary["can_submit"] is False
        entitlement = db_session.query(OrganizationEngineEntitlement).filter_by(organization_id=t.org.id).one()
        db_session.refresh(entitlement)
        assert entitlement.status == EntitlementStatus.ACTIVE  # viewing access untouched
    assert client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]["status_label"] == "Cancelled"
    statuses.change_status(db_session, t.sub.id, "active", reason="Renewed", actor=ADMIN)
    db_session.commit()
    assert _submit(client, t).status_code == 202
    events = _audit(db_session, "subscription.status", t.org)
    assert [(e.previous["status"], e.current["status"]) for e in events] == [
        ("active", "suspended"), ("suspended", "canceled"), ("canceled", "active")]
    assert all(e.reason for e in events)


def test_status_change_rules(db_session):
    t = _tenant(db_session, "status-rules")
    with pytest.raises(audit.ReasonRequired):
        statuses.change_status(db_session, t.sub.id, "suspended", reason=" ", actor=ADMIN)
    with pytest.raises(statuses.StatusError):
        statuses.change_status(db_session, t.sub.id, "active", reason="No change", actor=ADMIN)
    statuses.change_status(db_session, t.sub.id, "expired", reason="Ended", actor=ADMIN,
                           ends_at=datetime.now(timezone.utc) - timedelta(days=1))
    with pytest.raises(statuses.StatusError):
        statuses.change_status(db_session, t.sub.id, "active", reason="Renew without a date", actor=ADMIN)
    statuses.change_status(db_session, t.sub.id, "active", reason="Renewed", actor=ADMIN,
                           ends_at=datetime.now(timezone.utc) + timedelta(days=30))
    assert ledger.is_current(t.sub) and t.sub.status_changed_at is not None


def test_sweep_expires_ended_subscriptions_dry_run_first(client, db_session, enforced):
    t = _tenant(db_session, "sweep-expire", credits=3)
    t.sub.ends_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()
    assert _submit(client, t).json()["error"]["code"] == "subscription_expired"  # before the sweep, too
    planned = statuses.sweep(db_session, apply=False, actor=ADMIN)
    db_session.rollback()
    assert [item["action"] for item in planned] == ["expire"]
    assert db_session.get(OrganizationSubscription, t.sub.id).status == SubscriptionStatus.ACTIVE
    statuses.sweep(db_session, apply=True, actor=ADMIN)
    db_session.commit()
    assert db_session.get(OrganizationSubscription, t.sub.id).status == SubscriptionStatus.EXPIRED
    assert statuses.sweep(db_session, apply=True, actor=ADMIN) == []
    assert len(_audit(db_session, "subscription.expire", t.org)) == 1


def test_grace_period_of_two_days_closes_viewing_and_reactivation_reopens(client, db_session, monkeypatch):
    # Phase B: enforcement on and BILLING_VIEW_GRACE_DAYS=2 set by the owner (security review H1: unset by default).
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    monkeypatch.setattr(get_settings(), "billing_view_grace_days", 2)
    t = _tenant(db_session, "grace", credits=3)
    task_path = f"/api/v1/tasks/{_submit(client, t).json()['task']['id']}"
    statuses.change_status(db_session, t.sub.id, "canceled", reason="Customer left", actor=ADMIN)
    t.sub.status_changed_at = datetime.now(timezone.utc) - timedelta(days=1, hours=23)
    db_session.commit()
    assert statuses.sweep(db_session, apply=True, actor=ADMIN) == []  # inside the 2 days: still viewable
    assert client.get(task_path, headers=t.headers).status_code == 200
    t.sub.status_changed_at = datetime.now(timezone.utc) - timedelta(days=2, minutes=1)
    db_session.commit()
    actions = statuses.sweep(db_session, apply=True, actor=ADMIN)
    db_session.commit()
    assert actions[0]["action"] == "close_entitlements" and actions[0]["engines"] == ["firris"]
    assert client.get(task_path, headers=t.headers).status_code == 403
    statuses.change_status(db_session, t.sub.id, "active", reason="Came back", actor=ADMIN)
    db_session.commit()
    assert client.get(task_path, headers=t.headers).status_code == 200
    reopened = _audit(db_session, "subscription.status", t.org)[-1]
    assert reopened.current["entitlements_reopened"] == ["firris"]


# --- seats ------------------------------------------------------------------------------------------

def _provision(client, t, subject, role="analyst"):
    return client.post(f"/api/v1/organizations/{t.org.id}/administration/memberships", headers=t.headers,
                       json={"issuer": "https://issuer.test/", "subject": subject, "role": role,
                             "evidence_reference": "identity-ticket-1"})


def test_seat_limit_on_provisioning_and_reactivation(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "oidc_issuer_url", "https://issuer.test/")
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", False)  # this test is about "off"
    t = _tenant(db_session, "seats")  # Researcher: 1 seat, used by the owner
    assert _provision(client, t, "member-one").status_code == 201  # enforcement off: today's behaviour
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    refused = _provision(client, t, "member-two")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "seat_limit_reached"
    member = db_session.query(User).filter_by(subject="member-one").one()
    path = f"/api/v1/organizations/{t.org.id}/administration/memberships/{member.id}"
    assert client.patch(path, headers=t.headers, json={"role": "analyst", "status": "disabled"}).status_code == 200
    # Still 1 active of 1: re-enabling the member needs a free seat.
    assert client.patch(path, headers=t.headers, json={"role": "analyst", "status": "active"}).status_code == 409
    t.sub.seat_limit_override = 2
    db_session.commit()
    assert client.patch(path, headers=t.headers, json={"role": "analyst", "status": "active"}).status_code == 200
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()
    assert summary["seats"] == {"used": 2, "limit": 2, "level": 100}


def test_seat_limit_on_invitation_acceptance_leaves_invitation_unused(db_session, enforced):
    t = _tenant(db_session, "seats-invite")
    token = secrets.token_urlsafe(16)
    invitation = OrganizationInvitation(organization_id=t.org.id, email="new@example.test", role=MembershipRole.VIEWER,
                                        token_hash=invitation_token_hash(token),
                                        expires_at=datetime.now(timezone.utc) + timedelta(hours=2))
    db_session.add(invitation)
    db_session.commit()
    claims = OIDCClaims(issuer="https://identity.example.com", subject="invitee", email="new@example.test",
                        email_verified=True, display_name="Invitee")
    with pytest.raises(MembershipResolutionError) as caught:
        resolve_membership(db_session, claims=claims, policy="optional_invite", invitation_token=token,
                           organization_id=None)
    assert caught.value.code == "seat_limit_reached"
    db_session.rollback()
    assert db_session.get(OrganizationInvitation, invitation.id).accepted_at is None
    t.sub.seat_limit_override = 2
    db_session.commit()
    resolved = resolve_membership(db_session, claims=claims, policy="optional_invite", invitation_token=token,
                                  organization_id=None)
    assert resolved.membership.role == MembershipRole.VIEWER


def test_seat_limit_is_the_largest_of_the_organisations_plans(db_session):
    t = _tenant(db_session, "seats-two-families")
    db_session.add(OrganizationSubscription(organization_id=t.org.id, plan_key="megis.professional", family="megis",
                                            status=SubscriptionStatus.ACTIVE, source="test"))
    db_session.commit()
    assert limits.seat_limit(db_session, t.org.id) == 5
    assert limits.storage_limit(db_session, t.org.id) == 2_000_000_000 + 5_000_000_000


# --- storage ----------------------------------------------------------------------------------------

def test_storage_counts_result_files_and_datasets_and_blocks_only_when_configured(client, db_session, enforced, monkeypatch):
    t = _tenant(db_session, "storage", credits=5)
    created = _submit(client, t)
    task = db_session.get(Task, uuid.UUID(created.json()["task"]["id"]))
    db_session.add(Result(task_id=task.id, project_id=t.project.id, aoi_id=t.aoi.id, result_type="flood_extent_map",
                          output_files={"map": {"file_size_bytes": 1_400_000_000}, "pdf": {"file_size_bytes": 200_000_000},
                                        "legacy": "path/only.tif", "bad": {"file_size_bytes": "n/a"}}))
    db_session.add(ManagedDataset(series_id=uuid.uuid4(), version=1, organization_id=t.org.id, project_id=t.project.id,
                                  uploader_id=t.user.id, title="Rivers", category="hydrology", format="geojson",
                                  sha256="0" * 64, size_bytes=100_000_000, storage_key="k"))
    db_session.commit()
    assert limits.storage_used(db_session, t.org.id) == 1_700_000_000
    storage = client.get("/api/v1/billing/summary", headers=t.headers).json()["storage"]
    assert storage == {"used": 1_700_000_000, "limit": 2_000_000_000, "level": None}  # 85%: below the Q5 warning
    db_session.add(Result(task_id=task.id, project_id=t.project.id, aoi_id=t.aoi.id, result_type="fii", version=2,
                          output_files={"x": {"file_size_bytes": 150_000_000}}))
    db_session.commit()
    assert client.get("/api/v1/billing/summary", headers=t.headers).json()["storage"]["level"] == 90  # Q5: 90%
    assert _submit(client, t).status_code == 202  # 92.5%: warned, not blocked
    db_session.add(Result(task_id=task.id, project_id=t.project.id, aoi_id=t.aoi.id, result_type="fii", version=3,
                          output_files={"y": {"file_size_bytes": 250_000_000}}))
    db_session.commit()
    monkeypatch.setattr(get_settings(), "billing_storage_block_at_limit", False)
    assert _submit(client, t).status_code == 202  # the setting can still switch blocking off
    monkeypatch.setattr(get_settings(), "billing_storage_block_at_limit", True)  # Q5 (decided): block at 100%
    refused = _submit(client, t)
    assert refused.status_code == 402 and refused.json()["error"]["code"] == "storage_full"
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()
    assert summary["storage"]["level"] == 100 and summary["subscriptions"][0]["block_code"] == "storage_full"


# --- customer payments list -------------------------------------------------------------------------

def test_payments_list_is_for_owners_and_admins_of_the_same_organisation(client, db_session):
    t = _tenant(db_session, "pay-list")
    other = _tenant(db_session, "pay-list-other")
    viewer = _tenant(db_session, "pay-list-viewer", role=MembershipRole.VIEWER)
    paid = payments.record_top_up_payment(db_session, t.sub.id, credits=10, amount=100_000, method="cash",
                                          paid_on=date.today(), actor=ADMIN, key=_key(), note="admin-only note")
    payments.reverse_payment(db_session, paid.payment.id, reason="Bounced", actor=ADMIN, key=_key())
    payments.record_top_up_payment(db_session, other.sub.id, credits=10, amount=100_000, method="cash",
                                   paid_on=date.today(), actor=ADMIN, key=_key())
    db_session.commit()
    body = client.get("/api/v1/billing/payments", headers=t.headers).json()
    assert body["total"] == 2
    original = next(item for item in body["items"] if item["purpose"] == "top_up")
    assert original["reversed"] is True and original["family"] == "frris_wrris" and "note" not in original
    assert client.get("/api/v1/billing/payments", headers=viewer.headers).status_code == 403
    assert client.get("/api/v1/billing/payments", headers=other.headers).json()["total"] == 1


# --- backfill ---------------------------------------------------------------------------------------

def _bare_org(db, slug, *, engine=True, legacy=False):
    org = Organization(name=slug, slug=slug)
    db.add(org)
    db.flush()
    legacy_sub = None
    if legacy:
        legacy_sub = OrganizationSubscription(organization_id=org.id, status=SubscriptionStatus.ACTIVE, source="legacy")
        db.add(legacy_sub)
        db.flush()
    if engine:
        db.add(OrganizationEngineEntitlement(organization_id=org.id, engine_key="firris", status=EntitlementStatus.ACTIVE,
                                             source="legacy", subscription_id=legacy_sub.id if legacy_sub else None))
    db.flush()
    return org, legacy_sub


def _args(**overrides):
    return SimpleNamespace(**{"plan": [], "internal_org": [], "org_plan": [], "reason": None, "apply": False, **overrides})


def test_backfill_dry_run_then_apply(db_session):
    catalogue.seed_catalogue(db_session)
    plain, _ = _bare_org(db_session, "bf-plain")
    novarex, _ = _bare_org(db_session, "bf-novarex")
    legacy_org, legacy_sub = _bare_org(db_session, "bf-legacy", legacy=True)
    _bare_org(db_session, "bf-none", engine=False)
    done = _tenant(db_session, "bf-done")
    db_session.commit()

    report = run_backfill(db_session, _args(internal_org=["bf-novarex"]))
    actions = {step["organization"]: step["action"] for step in report["steps"]}
    assert report["mode"] == "dry-run"
    assert actions == {"bf-plain": "needs_plan", "bf-novarex": "create", "bf-legacy": "needs_plan",
                       "bf-none": "no_engine_access", "bf-done": "ok"}
    assert db_session.query(PlatformAudit).count() == 0
    with pytest.raises(backfill.BackfillError, match="bf-plain:frris_wrris"):
        run_backfill(db_session, _args(internal_org=["bf-novarex"], apply=True, reason="Phase B"))
    db_session.rollback()

    args = _args(plan=["frris_wrris=frris_wrris.professional"], internal_org=["bf-novarex"],
                 org_plan=["bf-legacy:frris_wrris=frris_wrris.academic"])
    preview = run_backfill(db_session, args)
    assert {s["organization"]: (s["action"], s["plan_key"]) for s in preview["steps"]
            if s["action"] not in {"ok", "no_engine_access"}} == {
        "bf-plain": ("create", "frris_wrris.professional"), "bf-novarex": ("create", "frris_wrris.internal"),
        "bf-legacy": ("adopt", "frris_wrris.academic")}
    assert db_session.query(OrganizationSubscription).filter_by(source="backfill").count() == 0

    with pytest.raises(SystemExit):
        run_backfill(db_session, _args(**{**vars(args), "apply": True}))
    run_backfill(db_session, _args(**{**vars(args), "apply": True, "reason": "Release Phase B backfill"}))
    for org, plan_key in ((plain, "frris_wrris.professional"), (novarex, "frris_wrris.internal"),
                          (legacy_org, "frris_wrris.academic")):
        sub = db_session.query(OrganizationSubscription).filter_by(organization_id=org.id, family="frris_wrris").one()
        entitlement = db_session.query(OrganizationEngineEntitlement).filter_by(organization_id=org.id).one()
        assert sub.plan_key == plan_key and sub.status == SubscriptionStatus.ACTIVE and entitlement.subscription_id == sub.id
    assert db_session.query(OrganizationSubscription).filter_by(organization_id=legacy_org.id).one().id == legacy_sub.id
    events = db_session.query(PlatformAudit).all()
    assert len(events) == 3 and {e.actor_label for e in events} == {"operator command: backfill-subscriptions"}
    assert all(e.reason == "Release Phase B backfill" for e in events)
    again = run_backfill(db_session, _args(plan=["frris_wrris=frris_wrris.professional"]))
    assert {step["action"] for step in again["steps"]} == {"ok", "no_engine_access"}
    assert done.sub is not None


def test_backfill_rejects_a_plan_from_another_family(db_session):
    catalogue.seed_catalogue(db_session)
    _bare_org(db_session, "bf-wrong")
    db_session.commit()
    with pytest.raises(backfill.BackfillError, match="not a frris_wrris plan"):
        backfill.plan(db_session, default_plans={"frris_wrris": "megis.professional"}, internal_orgs=[])
    with pytest.raises(backfill.BackfillError, match="not found"):
        backfill.plan(db_session, default_plans={}, internal_orgs=["no-such-org"])
