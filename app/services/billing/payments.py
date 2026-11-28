"""Manual payments, top-ups and credit adjustments (plan sections 3-4). No payment gateway in v1.

Every function here:
- takes the subscription row lock (`ledger.lock_subscription`), so ledger writes cannot race;
- is idempotent on the caller's request key (a double-clicked "Record payment" records one payment);
- writes `platform_audit` with a required reason or note;
- does not commit (the caller owns the transaction, so payment, ledger entry and audit land together).

A payment is never edited. A mistake is reversed by a new negative `reversal` payment with a reason; a
top-up reversal also removes the credits it added, as far as they are still unspent.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.billing import PAYMENT_METHODS, ConsoleRequestKey, CreditLedgerEntry, Payment
from app.models.platform import OrganizationSubscription, SubscriptionStatus
from app.services.billing import audit, catalogue, ledger, statuses

MAX_TOP_UP_CREDITS = 10_000
MAX_AMOUNT = 10_000_000_000  # TZS; a guard against a mistyped amount, far above any plan price


class PaymentError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class PaymentResult:
    payment: Payment
    entry: CreditLedgerEntry | None
    replayed: bool = False


def _today() -> date:
    return datetime.now(ledger._zone()).date()


def _check_key(key: str) -> str:
    if not key or len(key) > 160:
        raise PaymentError("request_key_invalid", "A request key of at most 160 characters is required.")
    return key


def _check_common(amount: int, method: str, paid_on: date, currency: str) -> None:
    if method not in PAYMENT_METHODS:
        raise PaymentError("payment_method_invalid", f"Method must be one of: {', '.join(PAYMENT_METHODS)}.")
    if not 0 < amount <= MAX_AMOUNT:
        raise PaymentError("payment_amount_invalid", "The amount must be a positive whole number of TZS.")
    if paid_on > _today():
        raise PaymentError("payment_date_invalid", "The payment date cannot be in the future.")
    if currency != catalogue.load_catalogue()["currency"]:
        raise PaymentError("payment_currency_invalid", f"Payments are recorded in {catalogue.load_catalogue()['currency']}.")


def _fingerprint(**fields) -> str:
    """The request a key was first used with (security review L5)."""
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def _key_reused() -> PaymentError:
    return PaymentError("request_key_reused", "This request key was already used for a different request.", 409)


def _claim(db: Session, key: str, action: str, fingerprint: str) -> bool:
    """Claim the key in the shared console namespace (independent review 3-4). Returns True when this exact
    request already claimed it (a replay), False when it is newly claimed. A different action or request is a
    409. A parallel claim waits on the primary key; the loser sees the winner's row, never a 500."""
    existing = db.query(ConsoleRequestKey).filter(ConsoleRequestKey.key == key).one_or_none()
    if existing is None:
        try:
            with db.begin_nested():
                db.add(ConsoleRequestKey(key=key, action=action, request_sha256=fingerprint))
                db.flush()
            return False
        except IntegrityError:
            existing = (db.query(ConsoleRequestKey).filter(ConsoleRequestKey.key == key)
                        .populate_existing().one())
    if existing.action != action or existing.request_sha256 != fingerprint:
        raise _key_reused()
    return True


def _insert_payment(db: Session, payment: Payment) -> None:
    """Belt and braces under the claim: a duplicate idempotency_key is a 409, never a 500 (independent review 4)."""
    try:
        with db.begin_nested():
            db.add(payment)
            db.flush()
    except IntegrityError as exc:
        raise _key_reused() from exc


def _replay(db: Session, key: str, subscription_id: uuid.UUID, purpose: str, fingerprint: str) -> PaymentResult | None:
    existing = db.query(Payment).filter(Payment.idempotency_key == key).one_or_none()
    if existing is None:
        return None
    if (existing.subscription_id != subscription_id or existing.purpose != purpose
            or (existing.request_sha256 is not None and existing.request_sha256 != fingerprint)):
        raise _key_reused()
    entry = db.query(CreditLedgerEntry).filter(CreditLedgerEntry.payment_id == existing.id).one_or_none()
    return PaymentResult(existing, entry, replayed=True)


def _payment_view(payment: Payment) -> dict:
    return {
        "payment_id": str(payment.id), "purpose": payment.purpose, "amount": payment.amount,
        "currency": payment.currency, "method": payment.method, "reference": payment.reference,
        "paid_on": payment.paid_on.isoformat(), "credits": payment.credits,
        "covers_from": payment.covers_from.isoformat() if payment.covers_from else None,
        "covers_until": payment.covers_until.isoformat() if payment.covers_until else None,
        "reverses_payment_id": str(payment.reverses_payment_id) if payment.reverses_payment_id else None,
    }


def _end_of(day: date) -> datetime:
    """Start of the day after `day`, in the billing timezone (an `ends_at` is exclusive)."""
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=ledger._zone())


def record_plan_payment(
    db: Session, subscription_id: uuid.UUID, *, amount: int, method: str, paid_on: date, covers_from: date,
    covers_until: date, actor: audit.Actor, key: str, reference: str | None = None, note: str | None = None,
    currency: str = "TZS",
) -> PaymentResult:
    """A payment for a plan period. A Pending or Expired subscription becomes Active; a fixed end date is
    extended to the end of the paid period. A Suspended subscription stays suspended (an admin decision)."""
    key = _check_key(key)
    subscription = ledger.lock_subscription(db, subscription_id)
    fingerprint = _fingerprint(purpose="plan_period", subscription=subscription.id, amount=amount, method=method,
                               paid_on=paid_on, covers_from=covers_from, covers_until=covers_until,
                               reference=_clean(reference), note=_clean(note), currency=currency)
    replayed = _replay(db, key, subscription.id, "plan_period", fingerprint)
    if replayed:
        return replayed
    if _claim(db, key, "payment.plan_period", fingerprint):
        return _replay(db, key, subscription.id, "plan_period", fingerprint) or _raise_reused()
    _check_common(amount, method, paid_on, currency)
    if covers_until < covers_from:
        raise PaymentError("payment_period_invalid", "The period must end on or after its start.")
    payment = Payment(
        organization_id=subscription.organization_id, subscription_id=subscription.id, amount=amount,
        currency=currency, method=method, reference=_clean(reference), paid_on=paid_on, purpose="plan_period",
        covers_from=covers_from, covers_until=covers_until, note=_clean(note),
        recorded_by_user_id=actor.user_id, idempotency_key=key, request_sha256=fingerprint,
    )
    _insert_payment(db, payment)
    reason = note or f"Plan payment {payment.reference or payment.id}"
    audit.record(db, actor, "payment.record", reason=reason, organization_id=subscription.organization_id,
                 target_type="payment", target_id=payment.id, current=_payment_view(payment))
    new_end = subscription.ends_at
    if new_end is not None and _end_of(covers_until) > new_end:
        new_end = _end_of(covers_until)
    reactivate = (subscription.status in {SubscriptionStatus.PENDING, SubscriptionStatus.EXPIRED}
                  and (new_end is None or new_end > datetime.now(ledger._zone())))
    if reactivate or new_end != subscription.ends_at:
        target = SubscriptionStatus.ACTIVE if reactivate else subscription.status
        statuses.change_status(db, subscription.id, target, ends_at=new_end, actor=actor,
                               reason=f"Payment recorded for {covers_from.isoformat()} to {covers_until.isoformat()}.",
                               action="subscription.payment_applied")
    return PaymentResult(payment, None)


def _top_up_price(db: Session, subscription: OrganizationSubscription) -> int | None:
    price = catalogue.current_price(db, subscription.plan_key) if subscription.plan_key else None
    return price.top_up_credit_price if price else None


def _refuse_unlimited(db: Session, subscription: OrganizationSubscription) -> None:
    if ledger.has_unlimited_credits(db, subscription):
        raise PaymentError("credits_unlimited", "This subscription's plan has unlimited credits.", 409)


def _check_credits(credits: int) -> None:
    if not 0 < credits <= MAX_TOP_UP_CREDITS:
        raise PaymentError("credits_invalid", f"Credits must be between 1 and {MAX_TOP_UP_CREDITS}.")


def record_top_up_payment(
    db: Session, subscription_id: uuid.UUID, *, credits: int, amount: int, method: str, paid_on: date,
    actor: audit.Actor, key: str, reference: str | None = None, note: str | None = None, currency: str = "TZS",
) -> PaymentResult:
    """A paid top-up: the payment and its `top_up` ledger entry (key `topup:<payment_id>`) in one
    transaction. The amount is not forced to the list price (a negotiated price is possible); the list
    price at recording time is kept beside it as `expected_amount`."""
    key = _check_key(key)
    subscription = ledger.lock_subscription(db, subscription_id)
    fingerprint = _fingerprint(purpose="top_up", subscription=subscription.id, credits=credits, amount=amount,
                               method=method, paid_on=paid_on, reference=_clean(reference), note=_clean(note),
                               currency=currency)
    replayed = _replay(db, key, subscription.id, "top_up", fingerprint)
    if replayed:
        return replayed
    if _claim(db, key, "payment.top_up", fingerprint):
        return _replay(db, key, subscription.id, "top_up", fingerprint) or _raise_reused()
    _check_common(amount, method, paid_on, currency)
    _check_credits(credits)
    _refuse_unlimited(db, subscription)
    unit = _top_up_price(db, subscription)
    payment = Payment(
        organization_id=subscription.organization_id, subscription_id=subscription.id, amount=amount,
        currency=currency, method=method, reference=_clean(reference), paid_on=paid_on, purpose="top_up",
        credits=credits, expected_amount=credits * unit if unit is not None else None, note=_clean(note),
        recorded_by_user_id=actor.user_id, idempotency_key=key, request_sha256=fingerprint,
    )
    _insert_payment(db, payment)
    ledger.ensure_period(db, subscription)
    entry = ledger.append_entry(db, subscription, kind="top_up", bucket="top_up", amount=credits,
                                key=f"topup:{payment.id}", payment_id=payment.id, actor_user_id=actor.user_id,
                                reason=_clean(note), metadata={"reference": payment.reference})
    audit.record(db, actor, "payment.record_top_up", reason=note or f"Top-up payment {payment.reference or payment.id}",
                 organization_id=subscription.organization_id, target_type="payment", target_id=payment.id,
                 current={**_payment_view(payment), "ledger_entry_id": str(entry.id),
                          "expected_amount": payment.expected_amount})
    return PaymentResult(payment, entry)


def record_test_payment(
    db: Session, subscription_id: uuid.UUID, *, amount: int, method: str, paid_on: date, actor: audit.Actor, key: str,
    reference: str | None = None, note: str | None = None, currency: str = "TZS",
) -> PaymentResult:
    """The owner's Abliner live test (TZS 500): a payment labelled test-only that adds NO credits and no plan period
    (owner decision 2026-11-21). No ledger entry (the ledger holds only non-zero credit movements); the audit row
    (payment.record_test) and the payment note carry the "TEST" label. Reversible like any payment."""
    key = _check_key(key)
    subscription = ledger.lock_subscription(db, subscription_id)
    note = _clean(note) or "TEST: payment-gateway live test, no credits"
    if not note.startswith("TEST:"):
        note = f"TEST: {note}"
    fingerprint = _fingerprint(purpose="test", subscription=subscription.id, amount=amount, method=method,
                               paid_on=paid_on, reference=_clean(reference), note=note, currency=currency)
    replayed = _replay(db, key, subscription.id, "test", fingerprint)
    if replayed:
        return replayed
    if _claim(db, key, "payment.test", fingerprint):
        return _replay(db, key, subscription.id, "test", fingerprint) or _raise_reused()
    _check_common(amount, method, paid_on, currency)
    payment = Payment(
        organization_id=subscription.organization_id, subscription_id=subscription.id, amount=amount,
        currency=currency, method=method, reference=_clean(reference), paid_on=paid_on, purpose="test",
        note=note, recorded_by_user_id=actor.user_id, idempotency_key=key, request_sha256=fingerprint,
    )
    _insert_payment(db, payment)
    audit.record(db, actor, "payment.record_test", reason=note, organization_id=subscription.organization_id,
                 target_type="payment", target_id=payment.id, current={**_payment_view(payment), "credits": 0})
    return PaymentResult(payment, None)


def reverse_payment(
    db: Session, payment_id: uuid.UUID, *, reason: str, actor: audit.Actor, key: str,
) -> PaymentResult:
    """Reverse a recorded payment with a new negative payment. For a top-up, also remove the credits it
    added, up to what is still unspent in the top-up bucket (the shortfall is recorded, not forced)."""
    reason = audit.require_reason(reason)
    key = _check_key(key)
    original = db.get(Payment, payment_id)
    if original is None:
        raise PaymentError("payment_not_found", "Payment not found.", 404)
    subscription = ledger.lock_subscription(db, original.subscription_id)
    fingerprint = _fingerprint(purpose="reversal", payment=original.id, reason=reason)
    replayed = _replay(db, key, subscription.id, "reversal", fingerprint)
    if replayed:
        return replayed
    if _claim(db, key, "payment.reversal", fingerprint):
        return _replay(db, key, subscription.id, "reversal", fingerprint) or _raise_reused()
    if original.purpose == "reversal":
        raise PaymentError("payment_not_reversible", "A reversal cannot itself be reversed.", 409)
    if db.query(Payment).filter(Payment.reverses_payment_id == original.id).first() is not None:
        raise PaymentError("payment_already_reversed", "This payment has already been reversed.", 409)
    reversal = Payment(
        organization_id=original.organization_id, subscription_id=original.subscription_id, amount=-original.amount,
        currency=original.currency, method=original.method, reference=original.reference, paid_on=_today(),
        purpose="reversal", credits=original.credits, reverses_payment_id=original.id, note=reason,
        recorded_by_user_id=actor.user_id, idempotency_key=key, request_sha256=fingerprint,
    )
    _insert_payment(db, reversal)
    entry = None
    shortfall = 0
    if original.purpose == "top_up" and original.credits:
        ledger.ensure_period(db, subscription)
        held = ledger.balances(db, subscription.id).top_up
        take = min(original.credits, held)
        shortfall = original.credits - take
        if take > 0:
            entry = ledger.append_entry(
                db, subscription, kind="adjustment", bucket="top_up", amount=-take, key=f"reverse:{reversal.id}",
                payment_id=reversal.id, actor_user_id=actor.user_id, reason=reason,
                metadata={"reverses_payment_id": str(original.id), "shortfall": shortfall})
    audit.record(db, actor, "payment.reverse", reason=reason, organization_id=original.organization_id,
                 target_type="payment", target_id=original.id, previous=_payment_view(original),
                 current={**_payment_view(reversal), "credits_removed": -(entry.amount) if entry else 0,
                          "credits_shortfall": shortfall})
    return PaymentResult(reversal, entry)


def grant_top_up(
    db: Session, subscription_id: uuid.UUID, *, credits: int, reason: str, actor: audit.Actor, key: str,
) -> CreditLedgerEntry:
    """Credits given without a payment (goodwill, a pilot, a manual refund of a software failure)."""
    reason = audit.require_reason(reason)
    key = _check_key(key)
    _check_credits(credits)
    subscription = ledger.lock_subscription(db, subscription_id)
    ledger_key = f"grant-topup:{key}"
    fingerprint = _fingerprint(kind="grant", subscription=subscription.id, credits=credits, reason=reason)
    existing = ledger.entry_by_key(db, ledger_key)
    if existing is not None:
        if existing.subscription_id != subscription.id or _ledger_fingerprint(existing) not in (None, fingerprint):
            raise _key_reused()
        return existing
    if _claim(db, key, "credits.grant", fingerprint):
        raise _key_reused()  # claimed by this request but no entry: cannot happen inside one transaction
    _refuse_unlimited(db, subscription)
    ledger.ensure_period(db, subscription)
    entry = ledger.append_entry(db, subscription, kind="top_up", bucket="top_up", amount=credits, key=ledger_key,
                                actor_user_id=actor.user_id, reason=reason,
                                metadata={"granted": True, "request_sha256": fingerprint})
    audit.record(db, actor, "credits.grant_top_up", reason=reason, organization_id=subscription.organization_id,
                 target_type="subscription", target_id=subscription.id,
                 current={"credits": credits, "ledger_entry_id": str(entry.id)})
    return entry


def adjust_credits(
    db: Session, subscription_id: uuid.UUID, *, amount: int, reason: str, actor: audit.Actor, key: str,
    bucket: str = "top_up",
) -> CreditLedgerEntry:
    """A signed correction with a reason. A negative adjustment cannot take a bucket below zero."""
    reason = audit.require_reason(reason)
    key = _check_key(key)
    if bucket not in {"monthly", "top_up"}:
        raise PaymentError("bucket_invalid", "Bucket must be 'monthly' or 'top_up'.")
    if amount == 0 or abs(amount) > MAX_TOP_UP_CREDITS:
        raise PaymentError("credits_invalid", f"The adjustment must be non-zero and at most {MAX_TOP_UP_CREDITS}.")
    subscription = ledger.lock_subscription(db, subscription_id)
    ledger_key = f"adjust:{key}"
    fingerprint = _fingerprint(kind="adjust", subscription=subscription.id, amount=amount, bucket=bucket, reason=reason)
    existing = ledger.entry_by_key(db, ledger_key)
    if existing is not None:
        if existing.subscription_id != subscription.id or _ledger_fingerprint(existing) not in (None, fingerprint):
            raise _key_reused()
        return existing
    if _claim(db, key, "credits.adjust", fingerprint):
        raise _key_reused()
    _refuse_unlimited(db, subscription)
    ledger.ensure_period(db, subscription)
    try:
        entry = ledger.append_entry(db, subscription, kind="adjustment", bucket=bucket, amount=amount, key=ledger_key,
                                    actor_user_id=actor.user_id, reason=reason,
                                    metadata={"request_sha256": fingerprint})
    except ledger.InsufficientCredits as exc:
        raise PaymentError("credits_insufficient", "The adjustment would take the balance below zero.", 409) from exc
    audit.record(db, actor, "credits.adjust", reason=reason, organization_id=subscription.organization_id,
                 target_type="subscription", target_id=subscription.id,
                 current={"amount": amount, "bucket": bucket, "ledger_entry_id": str(entry.id)})
    return entry


def _raise_reused():
    raise _key_reused()


def _ledger_fingerprint(entry: CreditLedgerEntry) -> str | None:
    return (entry.metadata_json or {}).get("request_sha256")


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None
