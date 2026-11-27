"""Payment intents: what a "Pay with Mobile Money" may buy, creating one, and the customer's view (plan §1-2, §8).

An intent is never a payment. Credits or a plan period are recorded only by settlement (completed at Abliner).
The full phone number is used for the one call to Abliner and never stored or logged.
"""
from __future__ import annotations

import base64
import logging
import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.http import PublicAPIError
from app.models.abliner import OPEN_STATUSES, PaymentIntent
from app.models.platform import BillingPlan, OrganizationSubscription
from app.services.abliner import phone as phones
from app.services.abliner.client import AblinerClient, AblinerError
from app.services.abliner.errors import map_error
from app.services.billing import catalogue, ledger, vat
from app.services.platform_admin.overview import paid_through

logger = logging.getLogger(__name__)

GATEWAY_MIN = 500
GATEWAY_MAX = 3_000_000
ORG_LIMIT = 5
ORG_WINDOW = timedelta(minutes=10)
CONTACT = "Contact NOVAREX to pay for this."


@dataclass(frozen=True)
class Offer:
    purpose: str
    available: bool
    amount: int | None
    currency: str
    credits: int | None = None
    covers_from: date | None = None
    covers_until: date | None = None
    unavailable_code: str | None = None
    unavailable_message: str | None = None


def _today() -> date:
    return datetime.now(timezone.utc).astimezone(ledger._zone()).date()


def _add_month(day: date) -> date:
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return day.replace(year=year, month=month, day=min(day.day, monthrange(year, month)[1]))


def _unavailable(purpose: str, code: str, message: str = CONTACT, amount: int | None = None) -> Offer:
    return Offer(purpose, False, amount, "TZS", unavailable_code=code, unavailable_message=message)


def offer(db: Session, subscription: OrganizationSubscription, purpose: str, today: date | None = None) -> Offer:
    plan = db.get(BillingPlan, subscription.plan_key) if subscription.plan_key else None
    if plan is None or plan.is_internal:
        return _unavailable(purpose, "internal_plan", "The Internal plan is not paid for.")
    if not catalogue.plan_on_current_catalogue(plan):
        # Security review M2: prices from an earlier catalogue file are never charged by Mobile Money. The owner
        # runs `billing.cli apply-catalogue --apply` before ABLINER_PAYMENTS_ENABLED=true.
        return _unavailable(purpose, "catalogue_not_applied",
                            "Mobile Money is not available for this plan yet. " + CONTACT)
    price = catalogue.current_price(db, plan.key)
    if purpose == "top_up":
        if not ledger.is_current(subscription):  # Q7: top-up credits are usable only with an active plan
            return _unavailable(purpose, "plan_not_active", "Renew your plan first: top-up credits can only be used with an active plan.")
        if price is None or price.top_up_credit_price is None:
            return _unavailable(purpose, "top_up_unavailable", "Top-ups are not offered for this plan yet. " + CONTACT)
        amount = vat.charge(catalogue.TOP_UP_PACK_CREDITS * price.top_up_credit_price)
        result = Offer(purpose, True, amount, price.currency, credits=catalogue.TOP_UP_PACK_CREDITS)
    elif purpose == "renewal":
        if plan.is_custom or price is None or price.monthly_price is None:
            return _unavailable(purpose, "contract_price")
        today = today or _today()
        last_paid = paid_through(db, subscription.id)
        start = max(today, last_paid + timedelta(days=1)) if last_paid else today
        result = Offer(purpose, True, vat.charge(price.monthly_price), price.currency, covers_from=start,
                       covers_until=_add_month(start) - timedelta(days=1))
    else:
        raise PublicAPIError(422, "purpose_invalid", "Choose a top-up or a plan renewal.")
    if result.currency != "TZS":
        return _unavailable(purpose, "currency_unsupported", amount=result.amount)
    if not GATEWAY_MIN <= result.amount <= GATEWAY_MAX:
        return _unavailable(purpose, "above_gateway_limit" if result.amount > GATEWAY_MAX else "below_gateway_limit",
                            amount=result.amount)
    return result


def _reference(intent_id: uuid.UUID) -> str:
    return "NOVA-" + base64.b32encode(intent_id.bytes[:5]).decode().rstrip("=")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create(db: Session, *, organization_id: uuid.UUID, user_id: uuid.UUID, subscription_id: uuid.UUID, purpose: str,
           phone_number: str, request_key: str, client: AblinerClient) -> tuple[PaymentIntent, bool]:
    """Create the intent, commit it, then call Abliner once and record the answer. Returns (intent, replayed).
    Raises PublicAPIError for anything the customer must see (the intent is committed first when one exists)."""
    if not get_settings().abliner_payments_enabled:
        raise PublicAPIError(404, "payments_unavailable", "Mobile Money payments are not available.")
    request_key = f"customer:{organization_id}:{request_key}"
    try:
        number = phones.normalise(phone_number)
    except phones.PhoneInvalid as exc:
        raise PublicAPIError(422, "invalid_phone", str(exc)) from None
    existing = db.query(PaymentIntent).filter(PaymentIntent.request_key == request_key).one_or_none()
    if existing is not None:
        # L7: the phone is part of the request. Only the masked form is kept (M4), so two numbers with the same
        # first 4 and last 3 digits replay the first intent, whose push already went to the first number.
        if (existing.created_by_user_id != user_id or existing.subscription_id != subscription_id
                or existing.purpose != purpose or existing.phone_masked != phones.masked(number)):
            raise PublicAPIError(409, "idempotency_key_reused", "This Idempotency-Key was already used for a different request.")
        return existing, True
    subscription = db.get(OrganizationSubscription, subscription_id)
    if subscription is None or subscription.organization_id != organization_id or subscription.family is None:
        raise PublicAPIError(404, "subscription_not_found", "Subscription not found.")
    quote = offer(db, subscription, purpose)
    if not quote.available:
        raise PublicAPIError(409, quote.unavailable_code, quote.unavailable_message)
    recent = db.query(PaymentIntent).filter(PaymentIntent.organization_id == organization_id,
                                            PaymentIntent.created_at > _now() - ORG_WINDOW).count()
    if recent >= ORG_LIMIT:
        raise PublicAPIError(429, "too_many_payments", "Too many payment attempts. Try again in a few minutes.")
    intent_id = uuid.uuid4()
    intent = PaymentIntent(
        id=intent_id, organization_id=organization_id, subscription_id=subscription.id, purpose=purpose,
        credits=quote.credits, covers_from=quote.covers_from, covers_until=quote.covers_until, amount=quote.amount,
        currency="TZS", phone_masked=phones.masked(number),
        reference=_reference(intent_id), idempotency_key=str(uuid.uuid4()), request_key=request_key,
        status="created", created_by_user_id=user_id)
    try:
        with db.begin_nested():
            db.add(intent)
            db.flush()
    except IntegrityError:
        db.rollback()
        raise PublicAPIError(409, "payment_in_progress",
                             "A Mobile Money payment for this is already waiting. Approve or cancel it on your phone first.") from None
    db.commit()  # the intent exists before the money call, so reconciliation can always find it
    try:
        deposit = client.create_deposit(amount=intent.amount, phone=number, reference=intent.reference,
                                        idempotency_key=intent.idempotency_key,
                                        callback_url=get_settings().abliner_callback_url)
    except AblinerError as exc:
        mapped = map_error(exc.code, exc.http_status)
        if exc.uncertain or exc.transaction_id:
            intent.status, intent.abliner_tx_id = "pending_unknown", exc.transaction_id
        else:
            intent.status, intent.failure_code = "failed", mapped.code
        db.commit()
        logger.warning("Abliner deposit not accepted intent=%s code=%s", intent.id, exc.code)
        if intent.status == "pending_unknown":
            return intent, False  # the customer sees "didn't respond … approve it if prompted"; reconciliation decides
        raise PublicAPIError(mapped.status, mapped.code, mapped.message) from None
    intent.status = "pending"
    intent.abliner_tx_id = deposit.id
    db.commit()
    logger.info("Abliner deposit pending intent=%s abliner=%s", intent.id, deposit.id)
    return intent, False


TEST_AMOUNT = 500


def create_test(db: Session, *, admin_user_id: uuid.UUID, subscription_id: uuid.UUID, phone_number: str, operator: str,
                client: AblinerClient) -> PaymentIntent:
    """The owner's TZS 500 live test (operator CLI only, works before ABLINER_PAYMENTS_ENABLED is switched on).
    Adds no credits when it completes; audited as a test (abliner.test_payment)."""
    from app.services.billing import audit
    from app.services.platform_admin.access import live_grant

    if live_grant(db, admin_user_id) is None:
        raise PublicAPIError(403, "platform_admin_required", "A NOVA ARI admin must start the test payment.")
    subscription = db.get(OrganizationSubscription, subscription_id)
    if subscription is None or subscription.family is None:
        raise PublicAPIError(404, "subscription_not_found", "Subscription not found.")
    try:
        number = phones.normalise(phone_number)
    except phones.PhoneInvalid as exc:
        raise PublicAPIError(422, "invalid_phone", str(exc)) from None
    intent_id = uuid.uuid4()
    intent = PaymentIntent(
        id=intent_id, organization_id=subscription.organization_id, subscription_id=subscription.id, purpose="test",
        amount=TEST_AMOUNT, currency="TZS", phone_masked=phones.masked(number),
        reference=_reference(intent_id), idempotency_key=str(uuid.uuid4()), request_key=f"operator:{intent_id}",
        status="created", created_by_user_id=admin_user_id)
    try:
        with db.begin_nested():
            db.add(intent)
            db.flush()
    except IntegrityError:
        db.rollback()
        raise PublicAPIError(409, "payment_in_progress", "A test payment for this subscription is already waiting.") from None
    audit.record(db, audit.Actor.command(f"abliner test-payment ({operator})"), "abliner.test_payment",
                 reason=f"TEST: Abliner live test, TZS {TEST_AMOUNT}, no credits", organization_id=subscription.organization_id,
                 target_type="payment_intent", target_id=intent.id, current={"reference": intent.reference, "amount": TEST_AMOUNT})
    db.commit()
    try:
        deposit = client.create_deposit(amount=TEST_AMOUNT, phone=number, reference=intent.reference,
                                        idempotency_key=intent.idempotency_key,
                                        callback_url=get_settings().abliner_callback_url)
    except AblinerError as exc:
        intent.status = "pending_unknown" if (exc.uncertain or exc.transaction_id) else "failed"
        intent.failure_code = None if intent.status == "pending_unknown" else map_error(exc.code, exc.http_status).code
        intent.abliner_tx_id = exc.transaction_id
        db.commit()
        logger.warning("Abliner test deposit not accepted intent=%s code=%s", intent.id, exc.code)
        return intent
    intent.status, intent.abliner_tx_id = "pending", deposit.id
    db.commit()
    logger.info("Abliner test deposit pending intent=%s abliner=%s", intent.id, deposit.id)
    return intent


# --- the customer's view ------------------------------------------------------------------------

def customer_message(intent: PaymentIntent) -> str:
    amount = f"TZS {intent.amount:,}"
    return {
        "created": f"Check your phone to approve the payment of {amount}.",
        "pending": f"Check your phone to approve the payment of {amount}.",
        "pending_unknown": ("We haven't heard back from the payment service yet. If your phone shows a prompt, "
                            "approve it; the result will appear here."),
        "completed": ("Test payment received. No credits were added." if intent.purpose == "test" else
                      "Payment received." + (f" {intent.credits} credits added." if intent.credits else " Your plan is renewed.")),
        "failed": map_error(intent.failure_code).message if intent.failure_code else "The payment was not completed.",
        "expired": ("The payment was not completed within 30 minutes, so nothing was added. "
                    "If money left your account, contact NOVAREX; otherwise you can try again."),
        "review": "We're checking this payment. NOVAREX will contact you.",
    }[intent.status]


def customer_status(intent: PaymentIntent) -> str:
    """Pending is never paid: only "completed" means credits or a plan period were recorded."""
    return {"created": "pending", "pending_unknown": "pending"}.get(intent.status, intent.status)


def is_open(intent: PaymentIntent) -> bool:
    return intent.status in OPEN_STATUSES
