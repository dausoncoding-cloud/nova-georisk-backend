"""Abliner M2: webhook -> settlement through the existing payments service, review, 30-minute expiry,
reconciliation, duplicates and races. Abliner is mocked; placeholders only."""
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.abliner import AblinerWebhookEvent, IntegrationStatus, PaymentIntent
from app.models.billing import CreditLedgerEntry, Payment, PlatformAudit
from app.services.abliner import reconcile, settlement
from app.services.abliner.client import AblinerClient
from app.services.platform_admin import access
from tests.integration.test_billing_credits import _tenant

@pytest.fixture(autouse=True, params=[False, True], ids=["enforcement-off", "enforcement-on"])
def enforcement(request, monkeypatch):
    """Every Abliner test runs with billing enforcement off (production today) and on."""
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", request.param)
    return request.param


SECRET = "whsec_TEST_placeholder"
PATH = "/api/v1/webhooks/abliner"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "abliner_webhook_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "abliner_api_key", SecretStr("tsl_live_TEST_placeholder"))


def _intent(db, t, *, purpose="top_up", status="pending", age_minutes=0, amount=100_000):
    today = datetime.now(timezone.utc).date()
    intent = PaymentIntent(
        organization_id=t.org.id, subscription_id=t.sub.id, purpose=purpose, amount=amount, currency="TZS",
        credits=10 if purpose == "top_up" else None,
        covers_from=today if purpose == "renewal" else None,
        covers_until=today + timedelta(days=29) if purpose == "renewal" else None,
        phone_masked="2557•••••678", phone_sha256="0" * 64, reference=f"NOVA-{uuid.uuid4().hex[:8].upper()}",
        idempotency_key=str(uuid.uuid4()), request_key=f"r-{uuid.uuid4()}", status=status,
        abliner_tx_id=f"tx_{uuid.uuid4().hex[:8]}", created_by_user_id=t.user.id,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes))
    db.add(intent)
    db.commit()
    return intent


def _event(intent, *, status="completed", amount=None, currency="TZS", event=None, webhook_id=None, reference=None):
    return {"id": webhook_id or f"evt_{uuid.uuid4()}_{status}", "event": event or f"transaction.{status}",
            "created_at": "2026-11-21T08:00:00.000Z",
            "data": {"id": str(uuid.uuid4()), "type": "deposit", "method": "mobile",
                     "amount": intent.amount if amount is None else amount, "currency": currency, "status": status,
                     "reference": "ABL1", "customer_reference": reference or intent.reference,
                     "provider_reference": "PRV-1" if status == "completed" else None,
                     "completed_at": "2026-11-21T08:00:00.000Z"}}


def _send(client, payload, *, ts=None, secret=SECRET, webhook_id=None):
    body = json.dumps(payload).encode()
    ts = str(int(ts if ts is not None else time.time()))
    signature = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "x-webhook-timestamp": ts, "x-webhook-signature": signature}
    if webhook_id is not False:
        headers["x-webhook-id"] = webhook_id or payload.get("id", "")
    return client.post(PATH, content=body, headers=headers)


def _payments(db, intent):
    return db.query(Payment).filter(Payment.subscription_id == intent.subscription_id).all()


def test_completed_webhook_settles_through_the_payments_service(client, db_session, caplog):
    caplog.set_level(logging.DEBUG)
    t = _tenant(db_session, "abw-done")
    intent = _intent(db_session, t)
    payload = _event(intent)
    response = _send(client, payload)
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    db_session.refresh(intent)
    assert intent.status == "completed" and intent.payment_id and intent.abliner_event_tx_id == payload["data"]["id"]
    payment = db_session.get(Payment, intent.payment_id)
    assert (payment.purpose, payment.method, payment.amount, payment.credits) == ("top_up", "mobile_money", 100_000, 10)
    assert payment.idempotency_key == f"abliner:{intent.id}" and payment.recorded_by_user_id is None
    entry = db_session.query(CreditLedgerEntry).filter_by(payment_id=payment.id).one()
    assert (entry.kind, entry.amount) == ("top_up", 10)
    event = db_session.query(PlatformAudit).filter_by(action="payment.record_top_up", target_id=str(payment.id)).one()
    assert event.actor_label == "system:abliner" and event.actor_user_id is None
    assert payload["data"]["id"] in event.reason
    labels = [item["label"] for item in client.get("/api/v1/billing/ledger", headers=t.headers).json()["items"]]
    assert "Top-up" in labels
    view = client.get(f"/api/v1/billing/abliner/payments/{intent.id}", headers=t.headers).json()
    assert view["status"] == "completed" and view["message"] == "Payment received. 10 credits added."
    assert db_session.get(IntegrationStatus, "abliner").last_webhook_event == "transaction.completed"
    # Never logged: the body, the signature, the secret or a phone number.
    for forbidden in (SECRET, payload["data"]["customer_reference"] + '"', "x-webhook-signature", "255712345678", '"amount"'):
        assert forbidden not in caplog.text, forbidden


def test_renewal_records_the_plan_period(client, db_session):
    t = _tenant(db_session, "abw-renew")
    intent = _intent(db_session, t, purpose="renewal", amount=150_000)
    assert _send(client, _event(intent)).status_code == 200
    db_session.refresh(intent)
    payment = db_session.get(Payment, intent.payment_id)
    assert (payment.purpose, payment.covers_from, payment.covers_until) == ("plan_period", intent.covers_from, intent.covers_until)


def test_duplicates_and_signatures(client, db_session):
    t = _tenant(db_session, "abw-dup")
    intent = _intent(db_session, t)
    payload = _event(intent)
    assert _send(client, payload).json() == {"status": "ok"}
    assert _send(client, payload).json() == {"status": "duplicate"}  # retried with a fresh timestamp, same id
    assert _send(client, payload, webhook_id=False).json() == {"status": "duplicate"}  # header missing: payload id
    assert len(_payments(db_session, intent)) == 1
    other = _intent(db_session, t, purpose="renewal", amount=150_000)
    bad = _send(client, _event(other), secret="whsec_wrong")
    assert bad.status_code == 401 and bad.json()["code"] == "invalid_signature"
    stale = _send(client, _event(other), ts=time.time() - 301)
    assert stale.status_code == 401 and stale.json()["code"] == "stale_timestamp"
    db_session.refresh(other)
    assert other.status == "pending" and db_session.query(AblinerWebhookEvent).count() == 1  # nothing stored
    status = db_session.get(IntegrationStatus, "abliner")
    db_session.refresh(status)
    assert status.last_error_code == "webhook_stale_timestamp"
    no_secret = client.post(PATH, content=b"{}", headers={"x-webhook-timestamp": "1"})
    assert no_secret.status_code == 401


def test_failed_unknown_and_checkout_events(client, db_session):
    t = _tenant(db_session, "abw-fail")
    intent = _intent(db_session, t)
    assert _send(client, _event(intent, status="failed")).status_code == 200
    db_session.refresh(intent)
    assert intent.status == "failed" and not _payments(db_session, intent)
    assert client.get(f"/api/v1/billing/abliner/payments/{intent.id}", headers=t.headers).json()["status"] == "failed"
    stranger = {"id": "evt_x", "event": "transaction.completed", "data": {"id": "u", "status": "completed",
                                                                          "customer_reference": "NOT-OURS", "amount": 1}}
    assert _send(client, stranger).status_code == 200
    assert db_session.get(AblinerWebhookEvent, "evt_x").outcome == "ignored"
    checkout = {"event": "checkout.paid", "id": "chk_1", "token": "t", "reference": "ORDER-1", "amount": 500,
                "currency": "TZS", "paid_at": "2026-11-21T08:00:00Z"}
    assert _send(client, checkout, webhook_id="whk_checkout_1").json() == {"status": "ok"}
    assert db_session.get(AblinerWebhookEvent, "whk_checkout_1").outcome == "ignored"


def test_mismatch_goes_to_review_and_an_admin_resolves_it(client, db_session):
    t = _tenant(db_session, "abw-review")
    admin_t = _tenant(db_session, "abw-review-admin", plan_key="frris_wrris.internal")
    access.grant(db_session, email=None, user_id=admin_t.user.id, reason="operator", operator="test")
    db_session.commit()
    intent = _intent(db_session, t)
    assert _send(client, _event(intent, amount=1_000)).status_code == 200
    db_session.refresh(intent)
    assert intent.status == "review" and "amount 1000 instead of 100000" in intent.review_reason
    assert not _payments(db_session, intent)
    assert db_session.query(PlatformAudit).filter_by(action="abliner.review", target_id=str(intent.id)).count() == 1
    view = client.get(f"/api/v1/billing/abliner/payments/{intent.id}", headers=t.headers).json()
    assert view["status"] == "review" and "NOVAREX will contact you" in view["message"]
    queue = client.get("/api/v1/platform-admin/mobile-payments", headers=admin_t.headers).json()
    assert [item["id"] for item in queue["items"]] == [str(intent.id)] and queue["items"][0]["phone"] == "2557•••••678"
    rows = client.get(f"/api/v1/platform-admin/customers?q={t.org.slug}", headers=admin_t.headers).json()["items"]
    assert "payment_review" in rows[0]["flags"]
    resolve = f"/api/v1/platform-admin/mobile-payments/{intent.id}/resolve"
    assert client.post(resolve, headers=admin_t.headers, json={"resolution": "no_action", "reason": ""}).status_code == 422
    assert client.post(resolve, headers=admin_t.headers, json={"resolution": "no_action",
                                                               "reason": "Customer confirmed a test amount"}).status_code == 200
    assert client.post(resolve, headers=admin_t.headers, json={"resolution": "no_action", "reason": "again"}).status_code == 409
    assert client.get("/api/v1/platform-admin/mobile-payments", headers=admin_t.headers).json()["total"] == 0
    assert client.get("/api/v1/platform-admin/mobile-payments", headers=t.headers).status_code == 403  # owners: no


class Remote:
    def __init__(self):
        self.items, self.calls, self.fail = {}, [], False

    def handler(self, request):
        self.calls.append(str(request.url))
        if self.fail:
            return httpx.Response(503, json={"status": "error", "code": "gateway_not_configured"})
        reference = request.url.params.get("customer_reference")
        return httpx.Response(200, json={"status": "success", "data": self.items.get(reference, [])})

    def client(self):
        return AblinerClient(transport=httpx.MockTransport(self.handler))


def _remote_item(intent, status, amount=None):
    return {"id": f"tx_{uuid.uuid4().hex[:6]}", "type": "deposit", "status": status,
            "amount": intent.amount if amount is None else amount, "currency": "TZS",
            "customer_reference": intent.reference, "provider_reference": "PRV-9", "completed_at": "2026-11-21T08:00:00Z"}


def test_reconciliation_settles_fails_waits_and_expires(db_session):
    t = _tenant(db_session, "abw-recon")
    remote = Remote()
    done = _intent(db_session, t, age_minutes=5)
    failed = _intent(db_session, t, purpose="renewal", amount=150_000, age_minutes=6)
    t2 = _tenant(db_session, "abw-recon-2")
    young = _intent(db_session, t2, age_minutes=1)                   # too young: not looked at
    waiting = _intent(db_session, t2, purpose="renewal", amount=150_000, age_minutes=10)
    t3 = _tenant(db_session, "abw-recon-3")
    old = _intent(db_session, t3, age_minutes=31)                    # no result after 30 minutes
    remote.items = {done.reference: [_remote_item(done, "completed")], failed.reference: [_remote_item(failed, "failed")],
                    waiting.reference: [_remote_item(waiting, "pending")]}
    dry = reconcile.run(db_session, remote.client(), apply=False)
    assert dry.counts == {"would_completed": 1, "would_failed": 1, "unchanged": 1, "would_expire": 1}
    db_session.refresh(done)
    assert done.status == "pending"
    report = reconcile.run(db_session, remote.client(), apply=True)
    assert report.counts == {"settled": 1, "failed": 1, "unchanged": 1, "expired": 1}
    for intent, expected in ((done, "completed"), (failed, "failed"), (young, "pending"), (waiting, "pending"),
                             (old, "expired")):
        db_session.refresh(intent)
        assert intent.status == expected, (intent.reference, intent.status)
    assert len(_payments(db_session, done)) == 1 and not _payments(db_session, old)


def test_abliner_errors_wait_until_the_expiry_window(db_session):
    t = _tenant(db_session, "abw-recon-err")
    remote = Remote()
    remote.fail = True
    young = _intent(db_session, t, age_minutes=10)
    t2 = _tenant(db_session, "abw-recon-err-2")
    old = _intent(db_session, t2, age_minutes=40)
    report = reconcile.run(db_session, remote.client(), apply=True)
    assert report.counts == {"error": 1, "expired": 1}
    db_session.refresh(young)
    db_session.refresh(old)
    assert (young.status, old.status) == ("pending", "expired")
    assert db_session.get(IntegrationStatus, "abliner").last_error_code == "reconcile_gateway_not_configured"


def test_completed_after_expiry_goes_to_review_never_silent_credit(client, db_session):
    t = _tenant(db_session, "abw-late")
    intent = _intent(db_session, t, age_minutes=31)
    reconcile.run(db_session, Remote().client(), apply=True)
    db_session.refresh(intent)
    assert intent.status == "expired"
    view = client.get(f"/api/v1/billing/abliner/payments/{intent.id}", headers=t.headers).json()
    assert view["status"] == "expired" and "not completed within 30 minutes" in view["message"]
    assert _send(client, _event(intent)).status_code == 200
    db_session.refresh(intent)
    assert intent.status == "review" and "after the payment was expired" in intent.review_reason
    assert not _payments(db_session, intent)


def test_webhook_before_and_after_reconciliation(client, db_session):
    t = _tenant(db_session, "abw-order")
    first = _intent(db_session, t, age_minutes=5)
    assert _send(client, _event(first)).status_code == 200            # webhook first
    remote = Remote()
    remote.items = {first.reference: [_remote_item(first, "completed")]}
    assert reconcile.run(db_session, remote.client(), apply=True).checked == 0   # nothing open any more
    second = _intent(db_session, t, purpose="renewal", amount=150_000, age_minutes=5)
    remote.items = {second.reference: [_remote_item(second, "completed")]}
    reconcile.run(db_session, remote.client(), apply=True)          # reconciliation first
    assert _send(client, _event(second)).json() == {"status": "ok"}    # the late webhook changes nothing
    db_session.refresh(second)
    assert second.status == "completed"
    assert len(_payments(db_session, first)) == 2  # one per intent, never more


def test_webhook_and_reconciliation_racing_settle_once(engine, db_session):
    t = _tenant(db_session, "abw-race")
    intent = _intent(db_session, t, age_minutes=5)
    Session = sessionmaker(bind=engine)
    remote_state = settlement.Remote(status="completed", tx_id="u-1", amount=intent.amount, currency="TZS",
                                     reference=intent.reference, provider_reference="PRV-R")
    barrier, outcomes = threading.Barrier(2), []

    def run(source):
        session = Session()
        try:
            barrier.wait()
            outcomes.append(settlement.apply(session, intent.id, settlement.Remote(**{**remote_state.__dict__, "source": source})))
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            outcomes.append(type(exc).__name__)
        finally:
            session.close()

    threads = [threading.Thread(target=run, args=(source,)) for source in ("webhook", "reconciliation")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(outcomes) == ["already", "settled"], outcomes
    db_session.expire_all()
    assert len(_payments(db_session, intent)) == 1


def test_parallel_duplicate_webhooks_store_and_settle_once(engine, db_session):
    from app.services.abliner import webhooks

    t = _tenant(db_session, "abw-race-dup")
    intent = _intent(db_session, t)
    payload = _event(intent)
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    headers = {"x-webhook-id": payload["id"], "x-webhook-timestamp": ts,
               "x-webhook-signature": hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()}
    Session = sessionmaker(bind=engine)
    barrier, outcomes = threading.Barrier(2), []

    def run():
        session = Session()
        try:
            barrier.wait()
            outcomes.append(webhooks.process(session, body, headers).outcome)
        except Exception as exc:  # noqa: BLE001
            outcomes.append(type(exc).__name__)
        finally:
            session.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(outcomes) == ["duplicate", "settled"], outcomes
    db_session.expire_all()
    assert len(_payments(db_session, intent)) == 1
