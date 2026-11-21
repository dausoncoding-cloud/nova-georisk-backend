"""Settlement: one entry point for the webhook, reconciliation and the operator CLI (plan §4).

Under the intent row lock:
- open intent + remote "completed" with the expected amount, currency and reference -> the existing payments
  service (actor "system:abliner", key "abliner:<intent id>"), so the ledger, platform audit, the shared
  console key namespace, fingerprints and reversal rules all apply; intent -> completed;
- any mismatch, or a "completed" arriving for an intent already expired or failed -> "review", no credits;
- remote "failed" -> failed, no credits;
- anything else -> unchanged.
Re-running is idempotent: a terminal intent returns at once, and the payment key replays.
Never logs a phone number, a payload or a header; only intent and Abliner IDs.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.abliner import OPEN_STATUSES, PaymentIntent
from app.services.billing import audit, ledger, payments

logger = logging.getLogger(__name__)

SYSTEM = audit.Actor(user_id=None, label="system:abliner")


@dataclass(frozen=True)
class Remote:
    status: str                      # completed, failed, pending or anything Abliner sends
    tx_id: str | None = None         # Abliner's data.id (UUID in webhooks, tx_... in the deposit reply)
    amount: int | None = None
    currency: str | None = None
    reference: str | None = None     # our reference, as Abliner's customer_reference
    provider_reference: str | None = None
    completed_at: datetime | None = None
    source: str = "webhook"          # webhook, reconciliation, operator


def _lock(db: Session, intent_id: uuid.UUID) -> PaymentIntent | None:
    return (db.query(PaymentIntent).filter(PaymentIntent.id == intent_id)
            .populate_existing().with_for_update().one_or_none())


def _review(db: Session, intent: PaymentIntent, why: str, remote: Remote) -> str:
    intent.status, intent.review_reason = "review", why[:500]
    intent.provider_reference = intent.provider_reference or (remote.provider_reference or None)
    db.flush()
    audit.record(db, SYSTEM, "abliner.review", reason=f"{why} (Abliner {remote.tx_id or intent.abliner_tx_id or '-'})",
                 organization_id=intent.organization_id, target_type="payment_intent", target_id=intent.id,
                 current={"remote_status": remote.status, "amount": remote.amount, "currency": remote.currency,
                          "source": remote.source})
    logger.warning("Abliner payment needs review intent=%s abliner=%s", intent.id, remote.tx_id or intent.abliner_tx_id)
    return "review"


def _paid_on(remote: Remote) -> date:
    moment = remote.completed_at or datetime.now(timezone.utc)
    return moment.astimezone(ledger._zone()).date()


def apply(db: Session, intent_id: uuid.UUID, remote: Remote) -> str:
    """Returns the outcome: settled, failed, review, unchanged or already. The caller commits."""
    intent = _lock(db, intent_id)
    if intent is None:
        return "unchanged"
    if remote.tx_id and remote.source == "webhook":
        intent.abliner_event_tx_id = intent.abliner_event_tx_id or remote.tx_id[:80]
    status = (remote.status or "").lower()
    if intent.status not in OPEN_STATUSES:
        if status == "completed" and intent.status in {"expired", "failed"}:
            # Money moved after we stopped waiting: never a silent credit; a person decides.
            return _review(db, intent, f"Abliner reported completed after the payment was {intent.status}.", remote)
        return "already"
    if status == "failed":
        intent.status, intent.failure_code = "failed", intent.failure_code or "abliner_failed"
        db.flush()
        logger.info("Abliner payment failed intent=%s abliner=%s", intent.id, remote.tx_id or intent.abliner_tx_id)
        return "failed"
    if status != "completed":
        return "unchanged"
    problems = []
    if remote.amount is not None and int(remote.amount) != intent.amount:
        problems.append(f"amount {remote.amount} instead of {intent.amount}")
    if (remote.currency or "TZS").upper() != intent.currency:
        problems.append(f"currency {remote.currency} instead of {intent.currency}")
    if remote.reference and remote.reference != intent.reference:
        problems.append("a different reference")
    if remote.amount is None:
        problems.append("no amount reported")
    if problems:
        return _review(db, intent, "Abliner completed payment does not match: " + "; ".join(problems) + ".", remote)
    tx = remote.tx_id or intent.abliner_tx_id or "-"
    common = dict(amount=intent.amount, method="mobile_money", paid_on=_paid_on(remote), actor=SYSTEM,
                  key=f"abliner:{intent.id}", reference=(remote.provider_reference or tx)[:255],
                  note=f"Abliner {tx}", currency=intent.currency)
    try:
        with db.begin_nested():
            if intent.purpose == "top_up":
                result = payments.record_top_up_payment(db, intent.subscription_id, credits=intent.credits, **common)
            else:
                result = payments.record_plan_payment(db, intent.subscription_id, covers_from=intent.covers_from,
                                                      covers_until=intent.covers_until, **common)
    except payments.PaymentError as exc:
        return _review(db, intent, f"The payment could not be recorded automatically ({exc.code}).", remote)
    intent.status, intent.payment_id = "completed", result.payment.id
    intent.completed_at = remote.completed_at or datetime.now(timezone.utc)
    intent.provider_reference = (remote.provider_reference or intent.provider_reference or None)
    db.flush()
    logger.info("Abliner payment settled intent=%s abliner=%s payment=%s", intent.id, tx, result.payment.id)
    return "settled"


def expire(db: Session, intent_id: uuid.UUID) -> str:
    """No result within the expiry window: expired, no credits. A later "completed" goes to review."""
    intent = _lock(db, intent_id)
    if intent is None or intent.status not in OPEN_STATUSES:
        return "already"
    intent.status, intent.failure_code = "expired", "no_result"
    db.flush()
    logger.info("Abliner payment expired intent=%s abliner=%s", intent.id, intent.abliner_tx_id)
    return "expired"
