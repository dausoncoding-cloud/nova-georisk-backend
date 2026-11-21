"""Q6 (decided 2026-11-21): a PDF payment receipt for every recorded payment, Abliner-settled ones included,
numbered without gaps, "not a TRA fiscal receipt", seller identity from settings and frozen on first drawing,
VAT line in every mode, test payments in their own TEST series. Customers (owners/admins, own organisation)
and NOVA ARI can download it."""
import io
import uuid
from datetime import date

import pytest
from pypdf import PdfReader

from app.core.config import get_settings
from app.models.receipts import PaymentReceipt
from app.services.billing import audit, payments, receipts
from app.services.platform_admin import access
from tests.integration.test_billing_credits import _tenant

ADMIN = audit.Actor(user_id=None, label="test admin")


@pytest.fixture(autouse=True, params=[False, True], ids=["enforcement-off", "enforcement-on"])
def enforcement(request, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", request.param)


@pytest.fixture()
def seller(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "seller_legal_name", "Seller Placeholder Ltd")
    monkeypatch.setattr(settings, "seller_tin", "100-000-000")
    monkeypatch.setattr(settings, "seller_address", "PO Box 0, Dar es Salaam")
    monkeypatch.setattr(settings, "seller_vat_mode", "none")
    return settings


def _key():
    return f"test:{uuid.uuid4()}"


def _text(content: bytes) -> str:
    return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


def _top_up(db, t, amount=150_000):
    return payments.record_top_up_payment(db, t.sub.id, credits=10, amount=amount, method="mobile_money",
                                          paid_on=date(2026, 11, 21), actor=ADMIN, key=_key(), reference="MM-1",
                                          note="admin-only note")


def test_every_payment_gets_a_gapless_number_and_reversals_none(db_session, seller):
    t = _tenant(db_session, "rc-numbers")
    first, second = _top_up(db_session, t), _top_up(db_session, t)
    reversal = payments.reverse_payment(db_session, second.payment.id, reason="Bounced", actor=ADMIN, key=_key())
    test = payments.record_test_payment(db_session, t.sub.id, amount=500, method="mobile_money", paid_on=date.today(),
                                        actor=ADMIN, key=_key())
    db_session.commit()
    a, b = receipts.for_payment(db_session, first.payment.id), receipts.for_payment(db_session, second.payment.id)
    assert (a.series, b.series) == ("receipt", "receipt") and b.number == a.number + 1
    assert receipts.for_payment(db_session, reversal.payment.id) is None
    assert receipts.number_text(receipts.for_payment(db_session, test.payment.id)).startswith("TEST-")
    # A rolled-back payment leaves no gap.
    _top_up(db_session, t)
    db_session.rollback()
    third = _top_up(db_session, t)
    db_session.commit()
    assert receipts.for_payment(db_session, third.payment.id).number == b.number + 1


def test_customer_downloads_the_receipt_and_the_seller_is_frozen(client, db_session, seller, monkeypatch):
    t = _tenant(db_session, "rc-customer")
    paid = _top_up(db_session, t)
    reversed_one = _top_up(db_session, t)
    payments.reverse_payment(db_session, reversed_one.payment.id, reason="Bounced", actor=ADMIN, key=_key())
    db_session.commit()
    listing = client.get("/api/v1/billing/payments", headers=t.headers).json()["items"]
    number = next(item["receipt_number"] for item in listing if item["id"] == str(paid.payment.id))
    assert number.startswith("R-") and all(item["receipt_number"] is None for item in listing if item["purpose"] == "reversal")
    response = client.get(f"/api/v1/billing/payments/{paid.payment.id}/receipt", headers=t.headers)
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="payment-receipt-{number}.pdf"'
    text = _text(response.content)
    for expected in ("Payment receipt", "not a TRA fiscal receipt", number, "21 Nov 2026", "Seller Placeholder Ltd",
                     "100-000-000", t.org.name, "top-up, 10 credits", "TZS 150,000", "VAT", "Not charged",
                     "Mobile Money, reference MM-1"):
        assert expected in text, expected
    assert "admin-only note" not in text
    # A later change of seller (for example to NOVAREX Ltd) never alters a receipt already issued...
    monkeypatch.setattr(get_settings(), "seller_legal_name", "Next Seller Ltd")
    assert "Seller Placeholder Ltd" in _text(client.get(f"/api/v1/billing/payments/{paid.payment.id}/receipt",
                                                       headers=t.headers).content)
    # ...but a new payment's receipt carries the new seller.
    later = _top_up(db_session, t)
    db_session.commit()
    assert "Next Seller Ltd" in _text(client.get(f"/api/v1/billing/payments/{later.payment.id}/receipt",
                                                 headers=t.headers).content)
    assert "REVERSED on" in _text(client.get(f"/api/v1/billing/payments/{reversed_one.payment.id}/receipt",
                                             headers=t.headers).content)


def test_receipts_are_scoped_to_owners_and_admins_of_the_organisation(client, db_session, seller):
    from app.models.identity import MembershipRole

    t = _tenant(db_session, "rc-scope")
    other = _tenant(db_session, "rc-scope-other")
    viewer = _tenant(db_session, "rc-scope-viewer", role=MembershipRole.VIEWER)
    paid = _top_up(db_session, t)
    db_session.commit()
    path = f"/api/v1/billing/payments/{paid.payment.id}/receipt"
    assert client.get(path, headers=other.headers).status_code == 404
    assert client.get(path, headers=viewer.headers).status_code == 403
    assert client.get(f"/api/v1/billing/payments/{uuid.uuid4()}/receipt", headers=t.headers).status_code == 404
    admin = _tenant(db_session, "rc-ari", plan_key="frris_wrris.internal")
    access.grant(db_session, email=None, user_id=admin.user.id, reason="operator", operator="test")
    db_session.commit()
    assert client.get(f"/api/v1/platform-admin/payments/{paid.payment.id}/receipt", headers=t.headers).status_code == 403
    console = client.get(f"/api/v1/platform-admin/payments/{paid.payment.id}/receipt", headers=admin.headers)
    assert console.status_code == 200 and "Payment receipt" in _text(console.content)
    numbers = {item["id"]: item["receipt_number"] for item in
               client.get("/api/v1/platform-admin/payments", headers=admin.headers).json()["items"]}
    assert numbers[str(paid.payment.id)].startswith("R-")


def test_refused_until_the_seller_is_configured(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "seller_legal_name", "")
    t = _tenant(db_session, "rc-unset")
    paid = _top_up(db_session, t)
    db_session.commit()
    response = client.get(f"/api/v1/billing/payments/{paid.payment.id}/receipt", headers=t.headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "receipts_not_configured"
    assert receipts.for_payment(db_session, paid.payment.id).seller is None


@pytest.mark.parametrize(("mode", "lines"), [
    ("inclusive", ("Amount before VAT", "TZS 127,119", "VAT 18%", "TZS 22,881 (included)", "TZS 150,000")),
    ("exclusive", ("Amount before VAT", "TZS 150,000", "VAT 18%", "TZS 27,000", "TZS 177,000")),
])
def test_vat_line_in_each_mode(client, db_session, seller, monkeypatch, mode, lines):
    monkeypatch.setattr(get_settings(), "seller_vat_mode", mode)
    t = _tenant(db_session, f"rc-vat-{mode}")
    paid = _top_up(db_session, t, amount=177_000 if mode == "exclusive" else 150_000)
    db_session.commit()
    text = _text(client.get(f"/api/v1/billing/payments/{paid.payment.id}/receipt", headers=t.headers).content)
    for expected in lines:
        assert expected in text, expected


def test_abliner_settled_and_test_payments_get_receipts(client, db_session, seller):
    """Abliner settlement goes through the same payment service, so it gets a receipt; a test payment is TEST."""
    t = _tenant(db_session, "rc-test")
    test = payments.record_test_payment(db_session, t.sub.id, amount=500, method="mobile_money", paid_on=date.today(),
                                        actor=audit.Actor(user_id=None, label="system:abliner"), key=f"abliner:{uuid.uuid4()}")
    db_session.commit()
    text = _text(client.get(f"/api/v1/billing/payments/{test.payment.id}/receipt", headers=t.headers).content)
    assert "TEST" in text and "no credits, not a sale" in text and "TEST-" in text
    assert db_session.query(PaymentReceipt).filter_by(payment_id=test.payment.id).one().series == "test"
