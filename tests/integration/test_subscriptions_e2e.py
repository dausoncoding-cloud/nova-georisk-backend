"""Subscriptions M5: end to end through the HTTP API, in release order.

Phase A (enforcement off, nothing changes) -> backfill (dry run, apply) -> Phase B (enforcement on) ->
a customer uses its allowance, hits the hard stop, still views results, asks for a top-up -> NOVA ARI
records the payment and closes the request -> analyses resume -> suspension and reactivation -> an
upgrade request -> the Internal plan is never charged -> every NOVA ARI action is in the audit log.
"""
import uuid
from datetime import date

from app.core.config import get_settings
from app.models.billing import CreditLedgerEntry, PlatformAudit
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement, OrganizationSubscription
from app.models.platform_admin import SubscriptionRequest
from app.services.billing import catalogue
from app.services.billing.cli import run_backfill
from app.services.platform_admin import access
from tests.integration.test_billing_accounts import _args
from tests.integration.test_billing_credits import _payload, _queue, _tenant  # noqa: F401

ADMIN = "/api/v1/platform-admin"


def _legacy_customer(db, slug):
    """An organisation as it exists before this release: engine access, no subscription."""
    t = _tenant(db, slug, subscribed=False)
    viewer = User(issuer="https://identity.billing.test/", subject=str(uuid.uuid4()), email=f"viewer@{slug}.test")
    db.add(viewer)
    db.flush()
    db.add(OrganizationMembership(organization_id=t.org.id, user_id=viewer.id, role=MembershipRole.VIEWER))
    db.commit()
    t.viewer_headers = {**t.headers, "X-Nova-User-Id": str(viewer.id), "X-Nova-Role": "viewer"}
    return t


def test_release_lifecycle_end_to_end(client, db_session, monkeypatch):
    settings = get_settings()
    catalogue.seed_catalogue(db_session)
    customer = _legacy_customer(db_session, "e2e-rufiji")
    novarex = _legacy_customer(db_session, "e2e-novarex")
    access.grant(db_session, email=None, user_id=novarex.user.id, reason="NOVA ARI operator", operator="e2e")
    db_session.commit()
    admin = novarex.headers
    key = lambda: {"Idempotency-Key": f"e2e-{uuid.uuid4()}"}  # noqa: E731

    # Phase A: deployed with enforcement off. Analyses run as today; nothing is charged.
    assert client.post("/api/v1/analyses", headers=customer.headers, json=_payload(customer)).status_code == 202
    assert db_session.query(CreditLedgerEntry).count() == 0

    # Backfill: dry run first, then apply.
    args = dict(plan=["frris_wrris=frris_wrris.professional"], internal_org=["e2e-novarex"])
    preview = run_backfill(db_session, _args(**args))
    assert {s["organization"]: s["action"] for s in preview["steps"]} == {"e2e-novarex": "create", "e2e-rufiji": "create"}
    run_backfill(db_session, _args(**args, apply=True, reason="Release Phase B backfill (e2e)"))
    # (Read from the database: opening the console would already grant this month's 30 credits.)
    sub_id = str(db_session.query(OrganizationSubscription.id).filter_by(organization_id=customer.org.id).scalar())
    # A small contract allowance keeps the test short (set before first use, so nothing to adjust).
    assert client.post(f"{ADMIN}/subscriptions/{sub_id}/plan", headers=admin,
                       json={"overrides": {"monthly_credits_override": 2}, "reason": "Pilot: 2 credits"}).status_code == 200

    # Phase B: enforcement on.
    monkeypatch.setattr(settings, "billing_enforcement_enabled", True)
    summary = client.get("/api/v1/billing/summary", headers=customer.headers).json()
    assert summary["enforcement_enabled"] is True
    assert summary["subscriptions"][0]["credits"]["granted"] == 2 and summary["subscriptions"][0]["can_submit"]
    tasks = [client.post("/api/v1/analyses", headers=customer.headers, json=_payload(customer, depth=d)) for d in (5.1, 5.2)]
    assert [t.status_code for t in tasks] == [202, 202]
    refused = client.post("/api/v1/analyses", headers=customer.headers, json=_payload(customer, depth=5.3))
    assert refused.status_code == 402 and refused.json()["error"]["code"] == "credits_exhausted"
    blocked = client.get("/api/v1/billing/summary", headers=customer.headers).json()["subscriptions"][0]
    assert blocked["credits"]["level"] == 100 and blocked["block_code"] == "credits_exhausted"
    assert blocked["block_message"].startswith("Your monthly analysis allowance has been reached.")
    task_id = tasks[0].json()["task"]["id"]
    assert client.get(f"/api/v1/tasks/{task_id}", headers=customer.viewer_headers).status_code == 200  # still viewable

    # The owner asks for a top-up; a viewer cannot; asking twice sends one request.
    request_body = {"subscription_id": sub_id, "kind": "top_up"}
    assert client.post("/api/v1/billing/requests", headers=customer.viewer_headers, json=request_body).status_code == 403
    first = client.post("/api/v1/billing/requests", headers=customer.headers, json=request_body)
    again = client.post("/api/v1/billing/requests", headers=customer.headers, json=request_body)
    assert first.status_code == 201 and first.json()["credits"] == 10 and again.json()["existing"] is True
    assert db_session.query(SubscriptionRequest).count() == 1

    # NOVA ARI sees it, records the payment, closes the request.
    row = client.get(f"{ADMIN}/customers?q=e2e-rufiji", headers=admin).json()["items"][0]
    assert {"request_open", "credits_low"} <= set(row["flags"])
    open_requests = client.get(f"{ADMIN}/requests", headers=admin).json()
    assert open_requests["total"] == 1 and open_requests["items"][0]["requested_by"] == customer.user.email
    paid = client.post(f"{ADMIN}/subscriptions/{sub_id}/payments", headers={**admin, **key()},
                       json={"purpose": "top_up", "amount": 100_000, "method": "mobile_money", "credits": 10,
                             "paid_on": date.today().isoformat(), "reference": "MP-E2E"})
    assert paid.status_code == 201
    closed = client.post(f"{ADMIN}/requests/{first.json()['id']}/close", headers=admin,
                         json={"outcome": "done", "reason": "Paid by mobile money MP-E2E"})
    assert closed.status_code == 200
    assert client.get("/api/v1/billing/requests", headers=customer.headers).json()[0]["status"] == "done"

    # Analyses resume, paid from the top-up bucket.
    resumed = client.post("/api/v1/analyses", headers=customer.headers, json=_payload(customer, depth=5.4))
    assert resumed.status_code == 202
    charge = db_session.query(CreditLedgerEntry).filter_by(task_id=uuid.UUID(resumed.json()["task"]["id"])).one()
    assert (charge.kind, charge.bucket) == ("charge", "top_up")

    # Suspension stops new analyses only; reactivation restores them.
    assert client.post(f"{ADMIN}/subscriptions/{sub_id}/status", headers=admin,
                       json={"status": "suspended", "reason": "Invoice 14 unpaid"}).status_code == 200
    suspended = client.post("/api/v1/analyses", headers=customer.headers, json=_payload(customer, depth=5.5))
    assert suspended.json()["error"]["code"] == "subscription_suspended"
    assert client.get(f"/api/v1/tasks/{task_id}", headers=customer.headers).status_code == 200
    entitlement = db_session.query(OrganizationEngineEntitlement).filter_by(organization_id=customer.org.id).one()
    db_session.refresh(entitlement)
    assert entitlement.status == EntitlementStatus.ACTIVE
    assert client.post(f"{ADMIN}/subscriptions/{sub_id}/status", headers=admin,
                       json={"status": "active", "reason": "Invoice 14 paid"}).status_code == 200
    assert client.post("/api/v1/analyses", headers=customer.headers, json=_payload(customer, depth=5.6)).status_code == 202

    # Upgrade request -> NOVA ARI changes the plan -> request closed.
    upgrade = client.post("/api/v1/billing/requests", headers=customer.headers,
                          json={"subscription_id": sub_id, "kind": "upgrade", "plan_key": "frris_wrris.academic"})
    assert upgrade.status_code == 201 and upgrade.json()["plan_name"] == "Academic / Department"
    assert client.post("/api/v1/billing/requests", headers=customer.headers,
                       json={"subscription_id": sub_id, "kind": "upgrade", "plan_key": "megis.academic"}).status_code == 422
    assert client.post(f"{ADMIN}/subscriptions/{sub_id}/plan", headers=admin,
                       json={"plan_key": "frris_wrris.academic", "overrides": {"monthly_credits_override": None},
                             "reason": "Upgrade requested by the owner"}).status_code == 200
    assert client.post(f"{ADMIN}/requests/{upgrade.json()['id']}/close", headers=admin,
                       json={"outcome": "done", "reason": "Plan changed"}).status_code == 200
    upgraded = client.get("/api/v1/billing/summary", headers=customer.headers).json()["subscriptions"][0]
    assert upgraded["plan_name"] == "Academic / Department" and upgraded["credits"]["granted"] == 2
    assert upgraded["limits"]["monthly_credits"] == 75 and upgraded["credits"]["remaining"] == 8 + 73  # 10 top-up - 2 runs, plus this month's difference

    # The Internal plan (NOVAREX) is never charged.
    for depth in (6.1, 6.2, 6.3):
        assert client.post("/api/v1/analyses", headers=novarex.headers, json=_payload(novarex, depth=depth)).status_code == 202
    internal_sub = db_session.query(Organization).filter_by(slug="e2e-novarex").one()
    assert db_session.query(CreditLedgerEntry).filter_by(organization_id=internal_sub.id).count() == 0

    # Every NOVA ARI action has a reason and an actor.
    events = db_session.query(PlatformAudit).filter(PlatformAudit.organization_id == customer.org.id).all()
    assert {"subscription.backfill_create", "subscription.change_plan", "payment.record_top_up", "request.close",
            "subscription.status"} <= {e.action for e in events}
    assert all(e.reason.strip() and (e.actor_user_id or e.actor_label) for e in events)
