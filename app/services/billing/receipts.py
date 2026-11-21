"""Payment receipts (Q6, decided 2026-11-21). See app/models/receipts.py for the numbering rules.

- `issue(db, payment)`: called by the payment service in the payment's own transaction (manual, Abliner-settled
  and test payments alike). Reversals get no receipt.
- `pdf(db, receipt)`: draws the PDF. The first drawing freezes the seller identity from the settings onto the
  receipt (a write on GET, like the billing summary's period roll-over); later drawings reuse it, so a change of
  seller name later never alters a receipt already issued. Refused while SELLER_LEGAL_NAME is unset.

The receipt says "Payment receipt - not a TRA fiscal receipt". No admin note or reason is ever printed.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.http import PublicAPIError
from app.models.billing import Payment
from app.models.identity import Organization
from app.models.platform import BillingPlan, OrganizationSubscription
from app.models.receipts import PaymentReceipt, ReceiptCounter
from app.services.billing import catalogue, vat

logger = logging.getLogger(__name__)

DISCLAIMER = "Payment receipt – not a TRA fiscal receipt"
METHOD = {"bank_transfer": "Bank transfer", "mobile_money": "Mobile Money", "cash": "Cash", "other": "Other"}


class ReceiptsNotConfigured(PublicAPIError):
    def __init__(self) -> None:
        super().__init__(503, "receipts_not_configured", "Receipts are not available yet. Contact NOVA ARI.")


def number_text(receipt: PaymentReceipt) -> str:
    return f"{'TEST' if receipt.series == 'test' else 'R'}-{receipt.number:06d}"


def issue(db: Session, payment: Payment) -> PaymentReceipt | None:
    if payment.purpose == "reversal":
        return None
    series = "test" if payment.purpose == "test" else "receipt"
    counter = db.query(ReceiptCounter).filter(ReceiptCounter.series == series).with_for_update().one_or_none()
    if counter is None:  # first receipt of a fresh database; the migration creates both rows in production
        counter = ReceiptCounter(series=series, last_number=0)
        db.add(counter)
        db.flush()
        counter = db.query(ReceiptCounter).filter(ReceiptCounter.series == series).with_for_update().one()
    counter.last_number += 1
    receipt = PaymentReceipt(payment_id=payment.id, organization_id=payment.organization_id, series=series,
                             number=counter.last_number, issued_at=datetime.now(timezone.utc))
    db.add(receipt)
    db.flush()
    return receipt


def for_payment(db: Session, payment_id) -> PaymentReceipt | None:
    return db.query(PaymentReceipt).filter(PaymentReceipt.payment_id == payment_id).one_or_none()


def _seller(receipt: PaymentReceipt) -> dict:
    if receipt.seller:
        return receipt.seller
    settings = get_settings()
    if not settings.seller_legal_name.strip():
        raise ReceiptsNotConfigured()
    receipt.seller = {"legal_name": settings.seller_legal_name.strip(), "tin": settings.seller_tin.strip(),
                      "address": settings.seller_address.strip(), "vat_mode": settings.seller_vat_mode,
                      "vat_rate_percent": settings.seller_vat_rate_percent}
    return receipt.seller


def item_text(db: Session, payment: Payment) -> str:
    subscription = db.get(OrganizationSubscription, payment.subscription_id)
    family = (subscription.family if subscription else None) or ""
    system = catalogue.load_catalogue()["families"].get(family, {}).get("name", "NOVA-GeoRisk")
    if payment.purpose == "test":
        return "TEST payment – payment-gateway check, no credits, not a sale"
    if payment.purpose == "top_up":
        return f"{system}: top-up, {payment.credits} credits"
    plan = db.get(BillingPlan, subscription.plan_key) if subscription and subscription.plan_key else None
    period = (f", {payment.covers_from:%d %b %Y} – {payment.covers_until:%d %b %Y}"
              if payment.covers_from and payment.covers_until else "")
    return f"{system}: {plan.name if plan else 'plan'} plan{period}"


def _split(amount: int, seller: dict) -> vat.Split:
    mode, rate = seller["vat_mode"], int(seller["vat_rate_percent"])
    if mode == "none" or rate == 0:
        return vat.Split(amount, 0, amount, mode, rate)
    tax = (amount * rate * 2 + (100 + rate)) // (2 * (100 + rate))
    return vat.Split(amount - tax, tax, amount, mode, rate)


def _tzs(value: int) -> str:
    return f"TZS {value:,}"


def pdf(db: Session, receipt: PaymentReceipt) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    payment = db.get(Payment, receipt.payment_id)
    seller = _seller(receipt)
    organization = db.get(Organization, payment.organization_id)
    reversal = db.query(Payment).filter(Payment.reverses_payment_id == payment.id).one_or_none()
    split = _split(payment.amount, seller)
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4, pageCompression=1)
    page.setTitle(f"Payment receipt {number_text(receipt)}")
    page.setAuthor(seller["legal_name"])
    width, height = A4
    left, y = 20 * mm, height - 22 * mm
    logo = get_settings().seller_logo_path
    if logo and os.path.isfile(logo):
        try:
            page.drawImage(logo, width - 60 * mm, height - 34 * mm, width=40 * mm, height=18 * mm,
                           preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001 - a broken logo file never stops a receipt
            logger.warning("Receipt logo could not be drawn")
    page.setFont("Helvetica-Bold", 18)
    page.drawString(left, y, "Payment receipt")
    y -= 7 * mm
    page.setFont("Helvetica", 10)
    page.drawString(left, y, DISCLAIMER)
    if receipt.series == "test":
        page.setFont("Helvetica-Bold", 28)
        page.setFillColorRGB(0.75, 0.1, 0.1)
        page.drawString(width - 70 * mm, height - 50 * mm, "TEST")
        page.setFillColorRGB(0, 0, 0)
    if reversal is not None:
        page.setFont("Helvetica-Bold", 14)
        page.setFillColorRGB(0.75, 0.1, 0.1)
        page.drawString(left, y - 9 * mm, f"REVERSED on {reversal.paid_on:%d %b %Y}")
        page.setFillColorRGB(0, 0, 0)
        y -= 9 * mm

    def row(label: str, value: str, bold: bool = False) -> None:
        nonlocal y
        y -= 7 * mm
        page.setFont("Helvetica", 10)
        page.drawString(left, y, label)
        page.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
        page.drawString(left + 45 * mm, y, value[:95])

    y -= 6 * mm
    row("Receipt number", number_text(receipt), bold=True)
    row("Payment date", f"{payment.paid_on:%d %b %Y}")
    row("Issued", f"{receipt.issued_at:%d %b %Y}")
    y -= 4 * mm
    row("Seller", seller["legal_name"], bold=True)
    if seller.get("tin"):
        row("TIN", seller["tin"])
    for line in (seller.get("address") or "").splitlines()[:3]:
        row("Address" if line == (seller.get("address") or "").splitlines()[0] else "", line)
    y -= 4 * mm
    row("Customer", organization.name if organization else "", bold=True)
    y -= 4 * mm
    row("Item", item_text(db, payment))
    if split.mode == "none" or split.rate == 0:
        row("Amount", _tzs(payment.amount))
        row("VAT", "Not charged")
    else:
        row("Amount before VAT", _tzs(split.net))
        row(f"VAT {split.rate}%", _tzs(split.vat) + (" (included)" if split.mode == "inclusive" else ""))
    row("Total paid", _tzs(payment.amount), bold=True)
    row("Paid by", METHOD.get(payment.method, payment.method) + (f", reference {payment.reference}" if payment.reference else ""))
    page.setFont("Helvetica", 8)
    page.drawString(left, 18 * mm, f"{DISCLAIMER}. Generated by NOVA-GeoRisk for {seller['legal_name']}.")
    page.showPage()
    page.save()
    return buffer.getvalue()


def filename(receipt: PaymentReceipt) -> str:
    return f"payment-receipt-{number_text(receipt)}.pdf"


def numbers(db: Session, payment_ids: list) -> dict:
    if not payment_ids:
        return {}
    rows = db.query(PaymentReceipt).filter(PaymentReceipt.payment_id.in_(payment_ids)).all()
    return {row.payment_id: number_text(row) for row in rows}


def response(db: Session, receipt: PaymentReceipt):
    """The PDF as a download; commits the frozen seller identity first."""
    from fastapi import Response

    content = pdf(db, receipt)
    db.commit()
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename(receipt)}"', "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff"})
