"""Subscriptions M4: NOVA ARI role, console API, audit with reason on every action, Add customer, tiles and
flags, usage tracking (API requests, downloads, data processed)."""
import inspect
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.main import app as api_app
from app.models.billing import CreditLedgerEntry, Payment, PlatformAudit
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement, OrganizationSubscription
from app.models.platform_admin import OrganizationUsageDaily, PlatformAdmin, SecurityAlert
from app.models.result import Result
from app.models.sessions import UserSession
from app.services.billing import catalogue, ledger, payments
from app.services.platform_admin import access, overview
from app.services.sessions.tracking import get_session_tracker
from app.services.usage import counters
from tests.integration.test_billing_credits import _payload, _queue, _tenant  # noqa: F401
from tests.integration.test_sessions import _sign_in, redis_client, stack  # noqa: F401
from tests.unit.test_sessions_local import CHROME_WINDOWS, FIREFOX_LINUX, SAFARI_IPHONE

BASE = "/api/v1/platform-admin"


def _admin(db, slug="nova-ari"):
    t = _tenant(db, slug, plan_key="frris_wrris.internal")
    t.user.display_name = "Asha Admin"
    db.commit()
    access.grant(db, email=None, user_id=t.user.id, reason="NOVA ARI operator", operator="test")
    db.commit()
    return t


def _key():
    return {"Idempotency-Key": f"test-{uuid.uuid4()}"}


def _audit(db, action):
    return db.query(PlatformAudit).filter(PlatformAudit.action == action).order_by(PlatformAudit.created_at).all()


# --- the role ---------------------------------------------------------------------------------------

def test_only_live_platform_admins_reach_the_console(client, db_session):
    owner = _tenant(db_session, "pa-owner")  # an organisation owner is not a platform admin
    gets = [route.path for route in api_app.routes
            if getattr(route, "path", "").startswith(BASE) and "GET" in getattr(route, "methods", set())]
    assert len(gets) >= 9
    for path in gets:
        concrete = path.replace("{organization_id}", str(owner.org.id))
        response = client.get(concrete, headers=owner.headers)
        assert response.status_code == 403 and response.json()["error"]["code"] == "platform_admin_required", path
    assert client.get(f"{BASE}/access").status_code in {401, 403}  # service call, no principal
    admin = _admin(db_session)
    body = client.get(f"{BASE}/access", headers=admin.headers).json()
    assert body == {"display_name": "Asha Admin", "email": admin.user.email, "organization_name": admin.org.name}
    access.revoke(db_session, email=None, user_id=admin.user.id, reason="Left the team", operator="test")
    db_session.commit()
    assert client.get(f"{BASE}/access", headers=admin.headers).status_code == 403  # next request, no cache
    assert [e.action for e in db_session.query(PlatformAudit).order_by(PlatformAudit.created_at)] == [
        "platform_admin.grant", "platform_admin.revoke"]


def test_the_role_is_granted_only_by_the_deploy_time_command(db_session):
    import app.api.admin_platform.router as console
    import app.api.v1.router as registry

    for module in (console, registry):
        source = inspect.getsource(module)
        assert "access.grant" not in source and "PlatformAdmin(" not in source
    admin = _admin(db_session)
    with pytest.raises(access.GrantError):
        access.grant(db_session, email=None, user_id=admin.user.id, reason="again", operator="test")
    with pytest.raises(ValueError):
        access.grant(db_session, email=admin.user.email, user_id=None, reason=" ", operator="test")
    assert db_session.query(PlatformAdmin).count() == 1


def test_a_disabled_admin_user_is_refused(client, db_session):
    admin = _admin(db_session)
    admin.user.is_active = False
    db_session.commit()
    assert client.get(f"{BASE}/overview", headers=admin.headers).status_code == 403


# --- Add customer -----------------------------------------------------------------------------------

def test_add_customer_creates_organisation_subscription_access_and_owner(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "oidc_issuer_url", "https://issuer.test/")
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    admin = _admin(db_session)
    body = {"name": "Rufiji Basin Office", "slug": "rufiji-basin", "family": "frris_wrris",
            "plan_key": "frris_wrris.professional", "reason": "Signed contract RB-2026-14",
            "owner_issuer": "https://issuer.test/", "owner_subject": "auth0|rufiji-owner",
            "owner_email": "owner@rufiji.example", "owner_name": "Rufiji Owner"}
    created = client.post(f"{BASE}/customers", headers=admin.headers, json=body)
    assert created.status_code == 201, created.text
    ids = created.json()
    org = db_session.get(Organization, uuid.UUID(ids["organization_id"]))
    sub = db_session.get(OrganizationSubscription, uuid.UUID(ids["subscription_id"]))
    entitlement = db_session.query(OrganizationEngineEntitlement).filter_by(organization_id=org.id).one()
    assert (org.slug, sub.plan_key, sub.status.value) == ("rufiji-basin", "frris_wrris.professional", "active")
    assert entitlement.subscription_id == sub.id and entitlement.status == EntitlementStatus.ACTIVE
    owner = db_session.get(OrganizationMembership, (org.id, uuid.UUID(ids["owner_user_id"])))
    assert owner.role == MembershipRole.OWNER
    events = [e for e in db_session.query(PlatformAudit).filter_by(organization_id=org.id)]
    assert {e.action for e in events} == {"organization.create", "subscription.create"}
    assert all(e.actor_user_id == admin.user.id and e.actor_label == "Asha Admin" for e in events)
    # The new owner can work at once (enforcement on): the plan's monthly credits are granted on first use.
    owner_headers = {"X-Nova-User-Id": ids["owner_user_id"], "X-Nova-Organization-Id": str(org.id), "X-Nova-Role": "owner"}
    summary = client.get("/api/v1/billing/summary", headers=owner_headers).json()["subscriptions"][0]
    assert summary["credits"]["granted"] == 30 and summary["can_submit"] is True
    again = client.post(f"{BASE}/customers", headers=admin.headers, json=body)
    assert again.status_code == 409 and again.json()["error"]["code"] == "slug_taken"
    no_reason = client.post(f"{BASE}/customers", headers=admin.headers, json={**body, "slug": "other", "reason": ""})
    assert no_reason.status_code == 422
    bad_issuer = client.post(f"{BASE}/customers", headers=admin.headers,
                             json={**body, "slug": "other-org", "owner_issuer": "https://evil.example/"})
    assert bad_issuer.json()["error"]["code"] == "owner_identity_invalid"
    assert db_session.query(Organization).filter_by(slug="other-org").first() is None
    second = client.post(f"{BASE}/customers/{org.id}/subscriptions", headers=admin.headers,
                         json={"family": "megis", "plan_key": "megis.researcher", "reason": "Added MEGIS"})
    assert second.status_code == 201
    duplicate = client.post(f"{BASE}/customers/{org.id}/subscriptions", headers=admin.headers,
                            json={"family": "megis", "plan_key": "megis.researcher", "reason": "Again"})
    assert duplicate.json()["error"]["code"] == "subscription_exists"


# --- table, flags, tiles ----------------------------------------------------------------------------

def test_customer_rows_flags_filters_and_tiles(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    admin = _admin(db_session)
    overdue = _tenant(db_session, "pa-overdue", plan_key="frris_wrris.academic")
    overdue.sub.starts_at = datetime.now(timezone.utc) - timedelta(days=10)
    expiring = _tenant(db_session, "pa-expiring", credits=4)
    expiring.sub.ends_at = datetime.now(timezone.utc) + timedelta(days=3)
    paid = _tenant(db_session, "pa-paid")
    db_session.commit()
    today = date.today()
    payments.record_plan_payment(db_session, paid.sub.id, amount=150_000, method="cash", paid_on=today,
                                 covers_from=today, covers_until=today + timedelta(days=30), actor=admin_actor(admin),
                                 key="pay-paid-1")
    db_session.add(SecurityAlert(organization_id=paid.org.id, user_id=paid.user.id, kind="new_device",
                                 detail={"browser": "Chrome", "os": "Windows"}))
    db_session.commit()
    for _ in range(4):
        assert client.post("/api/v1/analyses", headers=expiring.headers, json=_payload(expiring)).status_code == 202
    page = client.get(f"{BASE}/customers", headers=admin.headers).json()
    rows = {row["organization_slug"]: row for row in page["items"]}
    assert "payment_overdue" in rows["pa-overdue"]["flags"]
    assert rows["pa-overdue"]["plan_name"] == "Academic / Department" and rows["pa-overdue"]["users_limit"] == 10
    assert "expiring_soon" in rows["pa-expiring"]["flags"]
    assert (rows["pa-expiring"]["credits_used"], rows["pa-expiring"]["credits_available"]) == (4, 4)
    assert "credits_low" in rows["pa-expiring"]["flags"]
    assert rows["pa-paid"]["flags"] == ["new_device"]
    assert rows["nova-ari"]["is_internal"] is True and rows["nova-ari"]["flags"] == []  # Internal: never overdue
    assert rows["pa-paid"]["systems"] == ["FRRIS", "WRRIS"] and rows["pa-paid"]["storage_limit"] == 2_000_000_000
    only = client.get(f"{BASE}/customers?flag=payment_overdue", headers=admin.headers).json()
    assert {row["organization_slug"] for row in only["items"]} >= {"pa-overdue"}
    assert "pa-paid" not in {row["organization_slug"] for row in only["items"]}
    found = client.get(f"{BASE}/customers?q={paid.user.email}", headers=admin.headers).json()["items"]
    assert [row["organization_slug"] for row in found] == ["pa-paid"]
    tiles = client.get(f"{BASE}/overview", headers=admin.headers).json()
    assert tiles["expiring_soon"] == 1 and tiles["open_security_alerts"] == 1 and tiles["credits_used_this_month"] == 4
    assert tiles["active_subscriptions"] == 4 and tiles["payments_overdue"] == 1  # others are within the 7-day grace


def admin_actor(t):
    from app.services.billing import audit
    return audit.Actor(user_id=t.user.id, label="Asha Admin")


# --- actions ----------------------------------------------------------------------------------------

def test_every_action_needs_a_reason_and_writes_its_audit_row(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-actions", credits=2)
    assert client.post("/api/v1/analyses", headers=t.headers, json=_payload(t)).status_code == 202
    sub = f"{BASE}/subscriptions/{t.sub.id}"
    h = admin.headers
    assert client.post(f"{sub}/status", headers=h, json={"status": "suspended", "reason": ""}).status_code == 422
    suspended = client.post(f"{sub}/status", headers=h, json={"status": "suspended", "reason": "Unpaid invoice 14"})
    assert suspended.status_code == 200 and suspended.json()["status"] == "suspended"
    assert client.post("/api/v1/analyses", headers=t.headers, json=_payload(t)).json()["error"]["code"] == \
        "subscription_suspended"
    assert client.post(f"{sub}/status", headers=h, json={"status": "active", "reason": "Paid"}).status_code == 200
    upgraded = client.post(f"{sub}/plan", headers=h, json={"plan_key": "frris_wrris.professional",
                                                            "overrides": {"monthly_credits_override": None},
                                                            "reason": "Upgrade requested by email"})
    assert upgraded.status_code == 200 and upgraded.json()["plan_name"] == "Professional"
    adjustment = db_session.query(CreditLedgerEntry).filter_by(subscription_id=t.sub.id, kind="adjustment").one()
    assert adjustment.amount == 28 and adjustment.bucket == "monthly"  # 30 - 2 this month, at once
    wrong = client.post(f"{sub}/plan", headers=h, json={"plan_key": "megis.professional", "reason": "x"})
    assert wrong.json()["error"]["code"] == "plan_invalid"
    payment_body = {"purpose": "top_up", "amount": 100_000, "method": "mobile_money", "paid_on": date.today().isoformat(),
                    "credits": 10, "reference": "MP-77"}
    assert client.post(f"{sub}/payments", headers=h, json=payment_body).json()["error"]["code"] == \
        "idempotency_key_required"
    key = _key()
    first = client.post(f"{sub}/payments", headers={**h, **key}, json=payment_body)
    replay = client.post(f"{sub}/payments", headers={**h, **key}, json=payment_body)
    assert first.status_code == 201 and replay.json()["replayed"] is True
    assert replay.json()["payment"]["id"] == first.json()["payment"]["id"]
    assert db_session.query(Payment).count() == 1
    reversed_ = client.post(f"{BASE}/payments/{first.json()['payment']['id']}/reverse", headers={**h, **_key()},
                            json={"reason": "Mobile money reversal"})
    assert reversed_.status_code == 201 and reversed_.json()["payment"]["amount"] == -100_000
    added = client.post(f"{sub}/credits", headers={**h, **_key()}, json={"credits": 5, "reason": "Pilot goodwill"})
    assert added.status_code == 201
    adjusted = client.post(f"{sub}/adjustments", headers={**h, **_key()},
                           json={"amount": -1, "bucket": "top_up", "reason": "Duplicate goodwill"})
    assert adjusted.status_code == 201 and adjusted.json()["remaining"] == added.json()["remaining"] - 1
    actions_seen = [e.action for e in db_session.query(PlatformAudit).filter_by(organization_id=t.org.id)
                    .order_by(PlatformAudit.created_at)]
    assert actions_seen == ["subscription.status", "subscription.status", "subscription.change_plan",
                            "payment.record_top_up", "payment.reverse", "credits.grant_top_up", "credits.adjust"]
    for event in db_session.query(PlatformAudit).filter_by(organization_id=t.org.id):
        assert event.reason.strip() and event.actor_user_id == admin.user.id and event.actor_label == "Asha Admin"
        assert event.request_id  # the request it came from


def test_end_all_sessions_and_login_history_for_nova_ari(client, db_session, stack, monkeypatch):
    store, tracker, _ = stack
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-sessions")  # Researcher: 1 session
    first, _ = _sign_in(db_session, store, tracker, t, agent=FIREFOX_LINUX)
    second, second_ref = _sign_in(db_session, store, tracker, t, agent=CHROME_WINDOWS)
    alerts = db_session.query(SecurityAlert).filter_by(organization_id=t.org.id).all()
    assert len(alerts) == 1 and alerts[0].detail["browser"] == "Chrome"  # first sign-in ever: no alert
    client.app.dependency_overrides[get_session_tracker] = lambda: tracker
    try:
        assert client.get(f"{BASE}/customers/{t.org.id}/login-history", headers=admin.headers).status_code == 405
        history = client.post(f"{BASE}/customers/{t.org.id}/login-history", headers=admin.headers).json()
        assert [(i["browser"], i["result"], i["ended_earlier_sessions"]) for i in history["items"]] == [
            ("Chrome", "active", 1), ("Firefox", "replaced", 0)]
        assert history["items"][0]["ip_address"] == "41.59.10.20"  # NOVA ARI sees it (kept 30 days)
        assert len(_audit(db_session, "view.login_history")) == 1
        ended = client.post(f"{BASE}/customers/{t.org.id}/sessions/end", headers=admin.headers,
                            json={"reason": "Customer reported a lost laptop"})
        assert ended.json() == {"ended": 1} and store.get(second) is None
        assert tracker.ended_notice(second).startswith("You were signed out by NOVA ARI")
        row = db_session.get(UserSession, second_ref)
        db_session.refresh(row)
        assert row.end_reason == "ended_by_admin"
    finally:
        client.app.dependency_overrides.pop(get_session_tracker, None)
    open_alerts = client.get(f"{BASE}/security-alerts", headers=admin.headers).json()
    assert open_alerts["total"] == 1 and open_alerts["items"][0]["organization_name"] == t.org.name
    ack = client.post(f"{BASE}/security-alerts/{alerts[0].id}/acknowledge", headers=admin.headers,
                      json={"reason": "Confirmed with the customer: new office PC"})
    assert ack.status_code == 200
    assert client.get(f"{BASE}/security-alerts", headers=admin.headers).json()["total"] == 0
    again = client.post(f"{BASE}/security-alerts/{alerts[0].id}/acknowledge", headers=admin.headers,
                        json={"reason": "again"})
    assert again.json()["error"]["code"] == "alert_closed"


def test_plans_and_pricing_are_versioned_and_audited(client, db_session):
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-pricing")
    plans = {plan["key"]: plan for plan in client.get(f"{BASE}/plans", headers=admin.headers).json()}
    assert plans["frris_wrris.researcher"]["monthly_price"] == 150_000 and plans["frris_wrris.internal"]["is_internal"]
    changed = client.post(f"{BASE}/plans/frris_wrris.researcher/prices", headers=admin.headers,
                          json={"monthly_price": 175_000, "top_up_credit_price": 10_000, "reason": "2027 price list"})
    assert changed.status_code == 201 and changed.json()["price_version"] == 2
    assert client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]["monthly_price"] == 175_000
    internal = client.post(f"{BASE}/plans/frris_wrris.internal/prices", headers=admin.headers,
                           json={"monthly_price": 1, "reason": "x"})
    assert internal.status_code == 404
    limits = client.patch(f"{BASE}/plans/frris_wrris.researcher/limits", headers=admin.headers,
                          json={"monthly_credits": 20, "fields": ["monthly_credits"], "reason": "Q1 decided: 20 credits"})
    assert limits.status_code == 200 and limits.json()["limits"]["monthly_credits"] == 20
    event = _audit(db_session, "plan.limits")[0]
    assert event.previous["monthly_credits"] == 10 and event.current["monthly_credits"] == 20
    assert _audit(db_session, "plan.price")[0].previous["monthly_price"] == 150_000


def test_payments_page_and_audit_log_filters(client, db_session):
    admin = _admin(db_session)
    a = _tenant(db_session, "pa-pay-a")
    b = _tenant(db_session, "pa-pay-b")
    for t in (a, b):
        client.post(f"{BASE}/subscriptions/{t.sub.id}/payments", headers={**admin.headers, **_key()},
                    json={"purpose": "plan_period", "amount": 150_000, "method": "bank_transfer",
                          "paid_on": date.today().isoformat(), "covers_from": date.today().isoformat(),
                          "covers_until": (date.today() + timedelta(days=30)).isoformat(), "note": "Invoice 1"})
    page = client.get(f"{BASE}/payments", headers=admin.headers).json()
    assert page["total"] == 2 and {item["recorded_by"] for item in page["items"]} == {"Asha Admin"}
    assert client.get(f"{BASE}/payments?organization_id={a.org.id}", headers=admin.headers).json()["total"] == 1
    audit_page = client.get(f"{BASE}/audit?organization_id={a.org.id}&action=payment", headers=admin.headers).json()
    assert [item["action"] for item in audit_page["items"]] == ["payment.record"]
    assert audit_page["items"][0]["organization_name"] == a.org.name


# --- usage ------------------------------------------------------------------------------------------

def _wait_for_counts(redis_client, key, organization_id, **expected):
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        values = redis_client.hgetall(key)
        seen = {metric: sum(int(v) for f, v in values.items() if f.endswith(f"|{organization_id}|{metric}"))
                for metric in expected}
        if seen == expected:
            return
        time.sleep(0.02)
    raise AssertionError(f"usage counters did not reach {expected}: {seen}")


@pytest.fixture()
def usage_redis(redis_client, monkeypatch):
    import redis.asyncio as redis_asyncio

    key = f"nova:test:{uuid.uuid4().hex[:8]}:usage:buffer"
    monkeypatch.setattr(get_settings(), "usage_counting_enabled", True)
    monkeypatch.setattr(counters, "buffer_key", lambda: key)
    monkeypatch.setattr(counters, "_sync_client", lambda: redis_client)
    monkeypatch.setattr(counters, "_flush_client", lambda: redis_client)
    url = redis_client.connection_pool.connection_kwargs
    monkeypatch.setattr(counters, "_async_client", lambda: redis_asyncio.Redis(
        host=url["host"], port=url["port"], db=url["db"], decode_responses=True))
    yield redis_client, key
    for leftover in redis_client.scan_iter(f"{key}*"):
        redis_client.delete(leftover)


def test_api_requests_downloads_and_data_processed(client, db_session, usage_redis, tmp_path, monkeypatch):
    redis_client, key = usage_redis
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-usage")
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    created = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t))
    task_id = uuid.UUID(created.json()["task"]["id"])
    for name, size in (("export.csv", 1500), ("preview.png", 300)):
        (Path(tmp_path) / name).write_bytes(b"x" * size)
    result = Result(task_id=task_id, project_id=t.project.id, aoi_id=t.aoi.id, result_type="flood_extent_map",
                    output_files={"table": {"path": "export.csv", "file_size_bytes": 1500, "artifact_type": "export",
                                            "media_type": "text/csv"},
                                  "map": {"path": "preview.png", "file_size_bytes": 300, "artifact_type": "preview",
                                          "media_type": "image/png"}})
    db_session.add(result)
    db_session.commit()
    product = f"/api/v1/results/{result.id}/products"
    assert client.get(f"{product}/table", headers=t.headers).status_code == 200  # counted
    assert client.get(f"{product}/table", headers={**t.headers, "Range": "bytes=0-9"}).status_code == 206  # not
    assert client.get(f"{product}/map", headers=t.headers).status_code == 200  # preview: not counted
    client.get("/api/v1/billing/summary", headers=t.headers)
    client.get(f"{BASE}/overview", headers=admin.headers)  # the console's own requests are not counted
    _wait_for_counts(redis_client, key, t.org.id, api_requests=5, downloads=1)  # counters write in the background
    detail = client.get(f"{BASE}/customers/{t.org.id}", headers=admin.headers).json()  # flushes the buffer
    usage = detail["usage"]
    assert usage["downloads"] == 1 and usage["download_bytes"] == 1500
    assert usage["api_requests"] == 5  # submit, 3 product requests, summary; nothing from the console
    assert usage["analyses_run"] == 1 and usage["data_processed_bytes"] == 1800
    assert not redis_client.exists(key)
    row = db_session.query(OrganizationUsageDaily).filter_by(organization_id=t.org.id).one()
    assert row.downloads == 1
    assert db_session.query(OrganizationUsageDaily).filter_by(organization_id=admin.org.id).count() == 0


def test_usage_counting_never_breaks_a_request(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "usage_counting_enabled", True)

    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(counters, "_async_client", broken)
    monkeypatch.setattr(counters, "_sync_client", broken)
    monkeypatch.setattr(counters, "_flush_client", broken)
    t = _tenant(db_session, "pa-usage-down")
    assert client.get("/api/v1/billing/summary", headers=t.headers).status_code == 200
    counters.record_download(t.org.id, 10)
    assert counters.flush(db_session) == 0


def test_go_live_grace_stops_the_overdue_burst(db_session, monkeypatch):
    """Backfilled customers without payment records are judged from BILLING_OVERDUE_GRACE_FROM (go-live)."""
    from app.models.platform import BillingPlan
    t = _tenant(db_session, "pa-golive", plan_key="frris_wrris.academic")
    t.sub.starts_at = datetime.now(timezone.utc) - timedelta(days=60)
    db_session.commit()
    plan = db_session.get(BillingPlan, "frris_wrris.academic")
    today = date.today()
    assert overview.payment_overdue(db_session, t.sub, plan, today=today) is True
    monkeypatch.setattr(get_settings(), "billing_overdue_grace_from", today - timedelta(days=3))
    assert overview.payment_overdue(db_session, t.sub, plan, today=today) is False  # 3 days after go-live
    assert overview.payment_overdue(db_session, t.sub, plan, today=today + timedelta(days=4)) is False
    assert overview.payment_overdue(db_session, t.sub, plan, today=today + timedelta(days=5)) is True  # > 7 days
    # A recorded payment still moves the date forward as before.
    payments.record_plan_payment(db_session, t.sub.id, amount=750_000, method="cash", paid_on=today,
                                 covers_from=today, covers_until=today + timedelta(days=30),
                                 actor=admin_actor(_admin(db_session)), key="golive-pay-1")
    assert overview.payment_overdue(db_session, t.sub, plan, today=today + timedelta(days=37)) is False
    assert overview.payment_overdue(db_session, t.sub, plan, today=today + timedelta(days=38)) is True



# --- security review L1 / L7 ------------------------------------------------------------------------

def test_non_ascii_internal_secret_header_is_a_plain_404_not_a_500(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "usage_counting_enabled", True)
    response = client.get("/api/v1/no-such-route", headers={"X-Internal-Secret": "s\u00e9cret".encode("latin-1"),
                                                            "X-Nova-Organization-Id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_a_slow_or_down_redis_never_delays_a_request(client, db_session, monkeypatch):
    import asyncio
    import time

    monkeypatch.setattr(get_settings(), "usage_counting_enabled", True)

    class SlowAsync:
        async def hincrby(self, *_args):
            await asyncio.sleep(3)

    class SlowSync:
        def pipeline(self):
            return self

        def hincrby(self, *_args):
            return self

        def expire(self, *_args):
            return self

        def execute(self):
            time.sleep(3)

    t = _tenant(db_session, "pa-slow-redis")
    monkeypatch.setattr(counters, "_async_client", lambda: SlowAsync())
    started = time.monotonic()
    assert client.get("/api/v1/billing/summary", headers=t.headers).status_code == 200
    assert time.monotonic() - started < 1.5
    started = time.monotonic()
    counters.record_download(t.org.id, 100, client=SlowSync())
    assert time.monotonic() - started < 0.05

    def down():
        raise ConnectionError("redis down")

    monkeypatch.setattr(counters, "_async_client", down)
    monkeypatch.setattr(counters, "_sync_client", down)
    assert client.get("/api/v1/billing/summary", headers=t.headers).status_code == 200
    counters.record_download(t.org.id, 100)


# --- security review L2: typed, bounded overrides and limits ----------------------------------------

def test_overrides_and_limits_are_typed_and_bounded(client, db_session, monkeypatch):
    from app.services.platform_admin import actions as console_actions

    admin = _admin(db_session)
    t = _tenant(db_session, "pa-bounds")
    sub = f"{BASE}/subscriptions/{t.sub.id}/plan"
    bad = [{"monthly_credits_override": -1}, {"seat_limit_override": True}, {"seat_limit_override": 0},
           {"session_limit_override": 0}, {"monthly_credits_override": 10**12}, {"storage_bytes_override": 10**15},
           {"monthly_credits_override": "5"}, {"refund_on_data_failure_override": 1}, {"unknown_override": 3}]
    for overrides in bad:
        response = client.post(sub, headers=admin.headers, json={"overrides": overrides, "reason": "bounds"})
        assert response.status_code == 422, (overrides, response.text)
        created = client.post(f"{BASE}/customers", headers=admin.headers, json={
            "name": "Bounds Org", "slug": "bounds-org", "family": "frris_wrris", "plan_key": "frris_wrris.custom",
            "overrides": overrides, "reason": "bounds"})
        assert created.status_code == 422, (overrides, created.text)
    ok = client.post(sub, headers=admin.headers, json={"overrides": {"seat_limit_override": 3, "refund_on_data_failure_override": True},
                                                       "reason": "Contract terms"})
    assert ok.status_code == 200 and ok.json()["users_limit"] == 3
    db_session.refresh(t.sub)
    assert (t.sub.seat_limit_override, t.sub.refund_on_data_failure_override, t.sub.monthly_credits_override) == (3, True, None)
    cleared = client.post(sub, headers=admin.headers, json={"overrides": {"seat_limit_override": None}, "reason": "Back to plan"})
    assert cleared.status_code == 200 and cleared.json()["users_limit"] == 1  # only the field sent changed
    db_session.refresh(t.sub)
    assert t.sub.refund_on_data_failure_override is True
    for body in ({"seat_limit": 0, "fields": ["seat_limit"]}, {"monthly_credits": True, "fields": ["monthly_credits"]},
                 {"session_limit": 1000, "fields": ["session_limit"]}, {"storage_bytes": -1, "fields": ["storage_bytes"]}):
        response = client.patch(f"{BASE}/plans/frris_wrris.researcher/limits", headers=admin.headers, json={**body, "reason": "x"})
        assert response.status_code == 422, (body, response.text)
    # The services apply the same rules to every caller, not only the API.
    for overrides in ({"monthly_credits_override": True}, {"seat_limit_override": -2}, {"session_limit_override": 0}):
        with pytest.raises(console_actions.ActionError):
            console_actions.change_plan(db_session, t.sub.id, plan_key=None, overrides=overrides, reason="x",
                                        actor=admin_actor(admin))
        db_session.rollback()


def test_plan_change_top_up_counts_the_highest_allowance_once(client, db_session):
    """Security review L3: up (top-up), down (nothing taken back), up again (nothing added twice), then higher."""
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-updown")  # Researcher: 10 a month
    assert client.get("/api/v1/billing/summary", headers=t.headers).status_code == 200  # grants 10 this month
    path = f"{BASE}/subscriptions/{t.sub.id}/plan"

    def move(plan_key, **overrides):
        body = {"plan_key": plan_key, "reason": f"to {plan_key}"}
        if overrides:
            body["overrides"] = overrides
        assert client.post(path, headers=admin.headers, json=body).status_code == 200
        return [e.amount for e in db_session.query(CreditLedgerEntry).filter_by(subscription_id=t.sub.id, kind="adjustment")
                .order_by(CreditLedgerEntry.created_at)]

    assert move("frris_wrris.enterprise") == [240]            # 10 -> 250
    assert move("frris_wrris.researcher") == [240]            # down: nothing taken back
    assert move("frris_wrris.enterprise") == [240]            # up again: already had 250 this month
    assert move("frris_wrris.custom", monthly_credits_override=300) == [240, 50]  # higher still: only the difference
    assert ledger.balances(db_session, t.sub.id).monthly == 300


def test_an_idempotency_key_reused_with_a_different_request_is_refused(client, db_session):
    """Security review L5: the same key replays only the same request; anything else is a 409."""
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-fingerprint")
    path = f"{BASE}/subscriptions/{t.sub.id}"
    body = {"purpose": "top_up", "amount": 100_000, "method": "cash", "credits": 10, "paid_on": date.today().isoformat()}
    key = _key()
    first = client.post(f"{path}/payments", headers={**admin.headers, **key}, json=body)
    assert first.status_code == 201
    assert client.post(f"{path}/payments", headers={**admin.headers, **key}, json=body).json()["replayed"] is True
    changed = client.post(f"{path}/payments", headers={**admin.headers, **key}, json={**body, "amount": 10_000})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "request_key_reused"
    assert db_session.query(Payment).count() == 1
    grant_key = _key()
    assert client.post(f"{path}/credits", headers={**admin.headers, **grant_key}, json={"credits": 5, "reason": "Pilot"}).status_code == 201
    assert client.post(f"{path}/credits", headers={**admin.headers, **grant_key}, json={"credits": 5, "reason": "Pilot"}).status_code == 201
    assert client.post(f"{path}/credits", headers={**admin.headers, **grant_key}, json={"credits": 50, "reason": "Pilot"}).status_code == 409
    reverse_key = _key()
    reverse = f"{BASE}/payments/{first.json()['payment']['id']}/reverse"
    assert client.post(reverse, headers={**admin.headers, **reverse_key}, json={"reason": "Bounced"}).status_code == 201
    assert client.post(reverse, headers={**admin.headers, **reverse_key}, json={"reason": "Bounced"}).json()["replayed"] is True
    assert client.post(reverse, headers={**admin.headers, **reverse_key}, json={"reason": "Other"}).status_code == 409
    assert ledger.balances(db_session, t.sub.id).top_up == 5  # 10 paid - 10 reversed + 5 granted, each once


def test_non_ascii_internal_secret_is_refused_not_a_500(client):
    """Independent review 2: verify_internal_secret compares bytes; a non-ASCII header is 401, never 500."""
    response = client.get("/api/v1/billing/summary", headers={"X-Internal-Secret": "sécret".encode("latin-1"),
                                                               "X-Nova-User-Id": str(uuid.uuid4()),
                                                               "X-Nova-Organization-Id": str(uuid.uuid4()),
                                                               "X-Nova-Role": "owner"})
    assert response.status_code == 401


# --- independent review 1, 3, 4: one key namespace, validated keys, races --------------------------

def test_console_keys_use_the_submission_rule_and_one_namespace(client, db_session):
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-namespace")
    path = f"{BASE}/subscriptions/{t.sub.id}"
    top_up = {"purpose": "top_up", "amount": 100_000, "method": "cash", "credits": 10, "paid_on": date.today().isoformat()}
    for bad in ("short", "has space in it", "x" * 129, "semi;colon-key"):
        response = client.post(f"{path}/payments", headers={**admin.headers, "Idempotency-Key": bad}, json=top_up)
        assert response.status_code == 422 and response.json()["error"]["code"] == "idempotency_key_invalid", bad
    key = {"Idempotency-Key": "console-key-0001"}
    first = client.post(f"{path}/payments", headers={**admin.headers, **key}, json=top_up)
    assert first.status_code == 201
    # The same key for any other console action is a 409, not a second write.
    for url, body in ((f"{path}/credits", {"credits": 5, "reason": "Pilot"}),
                      (f"{path}/adjustments", {"amount": 1, "bucket": "top_up", "reason": "Fix"}),
                      (f"{BASE}/payments/{first.json()['payment']['id']}/reverse", {"reason": "Bounced"}),
                      (f"{path}/payments", {**top_up, "purpose": "plan_period", "covers_from": date.today().isoformat(),
                                             "covers_until": date.today().isoformat()})):
        response = client.post(url, headers={**admin.headers, **key}, json=body)
        assert response.status_code == 409 and response.json()["error"]["code"] == "request_key_reused", url
    credits_key = {"Idempotency-Key": "console-key-0002"}
    assert client.post(f"{path}/credits", headers={**admin.headers, **credits_key}, json={"credits": 5, "reason": "Pilot"}).status_code == 201
    assert client.post(f"{path}/payments", headers={**admin.headers, **credits_key}, json=top_up).status_code == 409
    assert client.post(f"{path}/adjustments", headers={**admin.headers, **credits_key},
                       json={"amount": 1, "bucket": "top_up", "reason": "Fix"}).status_code == 409
    assert db_session.query(Payment).count() == 1


def _parallel(engine, work):
    import threading
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    barrier, outcomes = threading.Barrier(2), []

    def run(index):
        session = Session()
        try:
            barrier.wait()
            outcomes.append(("ok", work(session, index)))
            session.commit()
        except Exception as exc:  # noqa: BLE001 - the outcome is what the test checks
            session.rollback()
            outcomes.append((type(exc).__name__, getattr(exc, "code", str(exc))))
        finally:
            session.close()

    threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    return outcomes


def test_parallel_payments_with_one_key_never_500(engine, db_session):
    admin = _admin(db_session)
    a = _tenant(db_session, "pa-race-a")
    b = _tenant(db_session, "pa-race-b")
    actor = admin_actor(admin)

    def pay(subscriptions):
        def work(session, index):
            return payments.record_top_up_payment(session, subscriptions[index], credits=10, amount=100_000, method="cash",
                                                  paid_on=date.today(), actor=actor, key="admin:race-key-1").replayed
        return work

    # One key, two different subscriptions at the same moment: one payment, the other a clean 409.
    outcomes = _parallel(engine, pay([a.sub.id, b.sub.id]))
    assert sorted(kind for kind, _ in outcomes) == ["PaymentError", "ok"], outcomes
    assert [code for kind, code in outcomes if kind == "PaymentError"] == ["request_key_reused"]
    # The same key and the same request twice at the same moment: one payment, the other a replay.
    outcomes = _parallel(engine, lambda session, index: payments.record_top_up_payment(
        session, a.sub.id, credits=10, amount=100_000, method="cash", paid_on=date.today(), actor=actor,
        key="admin:race-key-2").replayed)
    assert sorted(outcomes) == [("ok", False), ("ok", True)], outcomes
    db_session.expire_all()
    assert db_session.query(Payment).filter(Payment.idempotency_key.in_(["admin:race-key-1", "admin:race-key-2"])).count() == 2


def test_parallel_top_up_requests_never_500(engine, db_session, monkeypatch):
    from app.models.platform_admin import SubscriptionRequest
    from app.services.billing import requests as billing_requests

    catalogue.seed_catalogue(db_session)
    t = _tenant(db_session, "pa-race-requests")

    def ask(session, index):
        return billing_requests.create(session, organization_id=t.org.id, user_id=t.user.id, subscription_id=t.sub.id,
                                       kind="top_up").existing

    outcomes = _parallel(engine, ask)
    assert sorted(outcomes) == [("ok", False), ("ok", True)], outcomes
    # Force the check-then-insert race deterministically: the "is one open?" check misses the committed request.
    real = billing_requests._open_request
    calls = {"n": 0}

    def miss_first(session, subscription_id, kind):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(session, subscription_id, kind)

    monkeypatch.setattr(billing_requests, "_open_request", miss_first)
    created = billing_requests.create(db_session, organization_id=t.org.id, user_id=t.user.id, subscription_id=t.sub.id,
                                      kind="top_up")
    assert created.existing is True  # the unique index caught it; no IntegrityError reached the caller
    db_session.commit()
    assert db_session.query(SubscriptionRequest).filter_by(subscription_id=t.sub.id, status="open").count() == 1


def test_admin_reasons_never_reach_customers(client, db_session, monkeypatch):
    """Independent review 7 (owner decision): reasons are internal. Customers see fixed labels; the console sees both."""
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    admin = _admin(db_session)
    t = _tenant(db_session, "pa-reasons", credits=3)
    viewer = User(issuer="https://identity.billing.test/", subject=str(uuid.uuid4()), email="viewer@reasons.test")
    db_session.add(viewer)
    db_session.flush()
    db_session.add(OrganizationMembership(organization_id=t.org.id, user_id=viewer.id, role=MembershipRole.VIEWER))
    db_session.commit()
    viewer_headers = {**t.headers, "X-Nova-User-Id": str(viewer.id), "X-Nova-Role": "viewer"}
    secret = "INTERNAL-REASON-7f3a"
    assert client.post("/api/v1/analyses", headers=t.headers, json=_payload(t)).status_code == 202  # grant + charge
    path = f"{BASE}/subscriptions/{t.sub.id}"
    paid = client.post(f"{path}/payments", headers={**admin.headers, **_key()}, json={
        "purpose": "top_up", "amount": 100_000, "method": "cash", "credits": 10, "paid_on": date.today().isoformat(),
        "note": f"{secret} payment note", "reference": "REF-1"})
    assert paid.status_code == 201
    assert client.post(f"{path}/credits", headers={**admin.headers, **_key()}, json={"credits": 2, "reason": f"{secret} goodwill"}).status_code == 201
    assert client.post(f"{path}/adjustments", headers={**admin.headers, **_key()},
                       json={"amount": -1, "bucket": "top_up", "reason": f"{secret} correction"}).status_code == 201
    assert client.post(f"{path}/plan", headers=admin.headers,
                       json={"plan_key": "frris_wrris.professional", "overrides": {"monthly_credits_override": None},
                             "reason": f"{secret} upgrade"}).status_code == 200
    assert client.post(f"{BASE}/payments/{paid.json()['payment']['id']}/reverse", headers={**admin.headers, **_key()},
                       json={"reason": f"{secret} bounced"}).status_code == 201
    assert client.post(f"{path}/status", headers=admin.headers, json={"status": "suspended", "reason": f"{secret} unpaid"}).status_code == 200
    customer_paths = ["/api/v1/billing/summary", "/api/v1/billing/ledger", "/api/v1/billing/plans?family=frris_wrris",
                      "/api/v1/billing/payments", "/api/v1/billing/requests", "/api/v1/account/sessions",
                      "/api/v1/account/login-history"]
    for headers in (t.headers, viewer_headers):
        for customer_path in customer_paths:
            response = client.get(customer_path, headers=headers)
            assert secret not in response.text, (customer_path, headers["X-Nova-Role"])
    labels = [item["label"] for item in client.get("/api/v1/billing/ledger", headers=viewer_headers).json()["items"]]
    assert {"Monthly allowance", "Analysis", "Top-up", "Credits added by NOVAREX", "Credit adjustment by NOVAREX",
            "Plan change", "Top-up reversed"} <= set(labels), labels
    assert all("reason" not in item for item in client.get("/api/v1/billing/ledger", headers=t.headers).json()["items"])
    console = client.get(f"{BASE}/customers/{t.org.id}/ledger", headers=admin.headers).json()["items"]
    assert any((item["reason"] or "").startswith(secret) for item in console)  # NOVA ARI still sees them
