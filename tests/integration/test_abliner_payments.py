"""Abliner Mobile Money M1: offers, creating a payment, status; pending is never paid. Abliner is mocked with
httpx.MockTransport; placeholders only (never real keys)."""
import logging
import uuid

import httpx
import pytest
from pydantic import SecretStr

from app.api.v1.endpoints.abliner_payments import get_abliner_client
from app.core.config import get_settings
from app.models.platform import SubscriptionStatus
from app.models.abliner import PaymentIntent
from app.models.billing import CreditLedgerEntry, Payment
from app.models.identity import MembershipRole, OrganizationMembership, User
from app.services.abliner.client import AblinerClient
from tests.integration.test_billing_credits import _tenant

@pytest.fixture(autouse=True, params=[False, True], ids=["enforcement-off", "enforcement-on"])
def enforcement(request, monkeypatch):
    """Every Abliner test runs with billing enforcement off (production today) and on."""
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", request.param)
    return request.param


PHONE = "0712 345 678"
FULL = "255712345678"


class FakeAbliner:
    def __init__(self):
        self.calls = []
        self.reply = lambda request: httpx.Response(201, json={"status": "success", "data": {
            "id": f"tx_{len(self.calls)}", "status": "pending", "reference": "abl-ref"}})

    def handler(self, request):
        self.calls.append(request)
        return self.reply(request)

    def client(self):
        return AblinerClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture()
def abliner(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "abliner_payments_enabled", True)
    monkeypatch.setattr(settings, "abliner_api_key", SecretStr("tsl_live_TEST_placeholder"))
    monkeypatch.setattr(settings, "abliner_webhook_secret", SecretStr("whsec_TEST_placeholder"))
    fake = FakeAbliner()
    client.app.dependency_overrides[get_abliner_client] = fake.client
    yield fake
    client.app.dependency_overrides.pop(get_abliner_client, None)


def _key():
    return {"Idempotency-Key": f"pay-{uuid.uuid4()}"}


def _pay(client, t, purpose="top_up", phone=PHONE, headers=None, key=None):
    return client.post("/api/v1/billing/abliner/payments", headers={**(headers or t.headers), **(key or _key())},
                       json={"subscription_id": str(t.sub.id), "purpose": purpose, "phone": phone})


def test_offers_follow_plan_prices_and_the_gateway_limits(client, db_session, abliner, monkeypatch):
    t = _tenant(db_session, "ab-offers")
    offers = client.get(f"/api/v1/billing/abliner/offers?subscription_id={t.sub.id}", headers=t.headers).json()
    by = {item["purpose"]: item for item in offers["offers"]}
    assert offers["enabled"] is True
    # Q1: Researcher top-up 10 credits = TZS 150,000.
    assert (by["top_up"]["available"], by["top_up"]["amount"], by["top_up"]["credits"]) == (True, 150_000, 10)
    assert (by["renewal"]["available"], by["renewal"]["amount"]) == (True, 150_000) and by["renewal"]["covers_from"]
    offers_of = lambda: {i["purpose"]: i for i in client.get(  # noqa: E731
        f"/api/v1/billing/abliner/offers?subscription_id={t.sub.id}", headers=t.headers).json()["offers"]}
    # Q6 seller setting: with VAT "exclusive" the customer pays the price plus 18%.
    monkeypatch.setattr(get_settings(), "seller_vat_mode", "exclusive")
    assert (offers_of()["top_up"]["amount"], offers_of()["renewal"]["amount"]) == (177_000, 177_000)
    monkeypatch.setattr(get_settings(), "seller_vat_mode", "none")
    t.sub.plan_key = "frris_wrris.professional"  # Q1: every other FRRIS/WRRIS plan: TZS 100,000
    db_session.commit()
    assert offers_of()["top_up"]["amount"] == 100_000
    t.sub.plan_key, t.sub.family = "megis.professional", "megis"  # Q2: TZS 25,000 per credit
    db_session.commit()
    assert (offers_of()["top_up"]["available"], offers_of()["top_up"]["amount"]) == (True, 250_000)
    # Q7: top-up credits are usable only with an active plan; renewal stays on offer.
    t.sub.status = SubscriptionStatus.EXPIRED
    db_session.commit()
    expired = offers_of()
    assert expired["top_up"]["unavailable_code"] == "plan_not_active" and expired["renewal"]["available"] is True
    t.sub.status = SubscriptionStatus.ACTIVE
    db_session.commit()
    t.sub.plan_key = "megis.enterprise"  # TZS 3,500,000 a month: above Abliner's per-deposit maximum
    db_session.commit()
    by = {i["purpose"]: i for i in client.get(f"/api/v1/billing/abliner/offers?subscription_id={t.sub.id}",
                                                headers=t.headers).json()["offers"]}
    assert by["renewal"]["unavailable_code"] == "above_gateway_limit" and "NOVAREX" in by["renewal"]["unavailable_message"]
    t.sub.plan_key, t.sub.family = "frris_wrris.custom", "frris_wrris"
    db_session.commit()
    by = {i["purpose"]: i for i in client.get(f"/api/v1/billing/abliner/offers?subscription_id={t.sub.id}",
                                                headers=t.headers).json()["offers"]}
    assert by["renewal"]["unavailable_code"] == "contract_price"
    other = _tenant(db_session, "ab-offers-other")
    assert client.get(f"/api/v1/billing/abliner/offers?subscription_id={t.sub.id}", headers=other.headers).status_code == 404


def test_paying_creates_a_pending_intent_and_adds_nothing(client, db_session, abliner, caplog):
    caplog.set_level(logging.DEBUG)
    t = _tenant(db_session, "ab-pending")
    response = _pay(client, t)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending" and body["message"] == "Check your phone to approve the payment of TZS 150,000."
    assert body["phone"] == "2557•••••678" and FULL not in response.text
    assert len(abliner.calls) == 1 and b'"phone":"255712345678"' in abliner.calls[0].content
    intent = db_session.get(PaymentIntent, uuid.UUID(body["id"]))
    assert (intent.status, intent.abliner_tx_id, intent.amount, intent.credits) == ("pending", "tx_1", 150_000, 10)
    assert intent.reference.startswith("NOVA-") and intent.idempotency_key == abliner.calls[0].headers["idempotency-key"]
    # Nothing paid: no payment, no ledger credit, no top-up in the summary.
    assert db_session.query(Payment).count() == 0
    assert db_session.query(CreditLedgerEntry).filter_by(kind="top_up").count() == 0
    # The full number is stored nowhere and logged nowhere.
    row = {column.name: getattr(intent, column.name) for column in PaymentIntent.__table__.columns}
    assert FULL not in str(row) and FULL not in caplog.text and "0712" not in caplog.text
    assert client.get(f"/api/v1/billing/abliner/payments/{intent.id}", headers=t.headers).json()["status"] == "pending"


def test_one_open_payment_per_purpose_and_request_replay(client, db_session, abliner):
    t = _tenant(db_session, "ab-open")
    key = _key()
    first = _pay(client, t, key=key)
    assert _pay(client, t, key=key).json()["id"] == first.json()["id"]  # same click, same intent, one call
    assert len(abliner.calls) == 1
    second = _pay(client, t)
    assert second.status_code == 409 and second.json()["error"]["code"] == "payment_in_progress"
    assert _pay(client, t, purpose="renewal").status_code == 201  # another purpose is a separate payment
    reused = _pay(client, t, purpose="renewal", key=key)
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "idempotency_key_reused"


def test_roles_flag_scope_and_validation(client, db_session, abliner, monkeypatch):
    t = _tenant(db_session, "ab-roles")
    viewer = User(issuer="https://identity.billing.test/", subject=str(uuid.uuid4()), email="v@ab.test")
    db_session.add(viewer)
    db_session.flush()
    db_session.add(OrganizationMembership(organization_id=t.org.id, user_id=viewer.id, role=MembershipRole.VIEWER))
    db_session.commit()
    viewer_headers = {**t.headers, "X-Nova-User-Id": str(viewer.id), "X-Nova-Role": "viewer"}
    assert _pay(client, t, headers=viewer_headers).status_code == 403
    assert _pay(client, t, phone="0812345678").json()["error"]["code"] == "invalid_phone"
    no_key = client.post("/api/v1/billing/abliner/payments", headers=t.headers,
                         json={"subscription_id": str(t.sub.id), "purpose": "top_up", "phone": PHONE})
    assert no_key.json()["error"]["code"] == "idempotency_key_required"
    other = _tenant(db_session, "ab-roles-other")
    assert _pay(client, other, headers=other.headers, phone=PHONE).status_code == 201
    created = _pay(client, t).json()
    assert client.get(f"/api/v1/billing/abliner/payments/{created['id']}", headers=other.headers).status_code == 404
    monkeypatch.setattr(get_settings(), "abliner_payments_enabled", False)
    off = _pay(client, t, purpose="renewal")
    assert off.status_code == 404 and off.json()["error"]["code"] == "payments_unavailable"
    assert len(abliner.calls) == 2  # nothing reached Abliner for the refused requests


def test_organisation_rate_limit(client, db_session, abliner):
    t = _tenant(db_session, "ab-rate")
    for index in range(5):
        db_session.add(PaymentIntent(organization_id=t.org.id, subscription_id=t.sub.id, purpose="top_up", credits=10,
                                     amount=100_000, currency="TZS", phone_masked="2557•••••678", phone_sha256="0" * 64,
                                     reference=f"NOVA-RATE{index}", idempotency_key=str(uuid.uuid4()),
                                     request_key=f"r-{uuid.uuid4()}", status="failed", created_by_user_id=t.user.id))
    db_session.commit()
    response = _pay(client, t)
    assert response.status_code == 429 and response.json()["error"]["code"] == "too_many_payments"


@pytest.mark.parametrize("reply, status, code, intent_status", [
    (lambda r: httpx.Response(409, json={"status": "error", "code": "ussd_session_busy"}), 409, "phone_busy", "failed"),
    (lambda r: httpx.Response(422, json={"status": "error", "code": "daily_limit_exceeded"}), 422, "gateway_daily_limit", "failed"),
    (lambda r: httpx.Response(401, json={"status": "error", "code": "invalid_request_signature"}), 503,
     "gateway_misconfigured", "failed"),
    (lambda r: httpx.Response(502, json={"status": "error", "code": "provider_error", "transaction_id": "tx_9"}), 201,
     None, "pending_unknown"),
])
def test_abliner_refusals_and_uncertain_answers(client, db_session, abliner, reply, status, code, intent_status):
    t = _tenant(db_session, f"ab-err-{uuid.uuid4().hex[:6]}")
    abliner.reply = reply
    response = _pay(client, t)
    assert response.status_code == status, response.text
    if code:
        assert response.json()["error"]["code"] == code
    intent = db_session.query(PaymentIntent).filter_by(organization_id=t.org.id).one()
    db_session.refresh(intent)
    assert intent.status == intent_status and len(abliner.calls) == 1
    assert db_session.query(Payment).count() == 0


def test_a_timeout_is_pending_unknown_not_failed_and_not_retried(client, db_session, abliner):
    t = _tenant(db_session, "ab-timeout")

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    abliner.reply = slow
    response = _pay(client, t)
    assert response.status_code == 201 and response.json()["status"] == "pending"
    assert "haven't heard back" in response.json()["message"]
    intent = db_session.query(PaymentIntent).filter_by(organization_id=t.org.id).one()
    db_session.refresh(intent)
    assert intent.status == "pending_unknown" and len(abliner.calls) == 1
    # Still one open payment: the customer cannot start a second prompt while this one is unresolved.
    assert _pay(client, t).json()["error"]["code"] == "payment_in_progress"
