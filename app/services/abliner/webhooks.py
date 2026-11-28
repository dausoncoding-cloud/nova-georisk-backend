"""Abliner webhook verification and processing (plan §3).

Order: secret configured -> timestamp within ±300 s -> hex HMAC-SHA256 over "<timestamp>.<raw body>" keyed with
ABLINER_WEBHOOK_SECRET, compared in constant time on bytes -> dedupe on the webhook ID -> settle under the
intent row lock. Nothing is parsed or stored before the signature is verified. Nothing from the request
(body, headers, phone numbers) is logged; only the webhook, intent and Abliner IDs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.abliner import AblinerWebhookEvent, PaymentIntent
from app.services.abliner import settlement
from app.services.integrations import status as integration_status

logger = logging.getLogger(__name__)

TOLERANCE_SECONDS = 300
MAX_BODY_BYTES = 64 * 1024


class Rejected(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


@dataclass(frozen=True)
class Outcome:
    status: str          # ok, duplicate, retry (answered 503 so Abliner redelivers)
    outcome: str         # settled, failed, review, unchanged, already, ignored, duplicate, error


def _header(headers, name: str) -> str:
    value = headers.get(name)
    return value if isinstance(value, str) else ""


def verify(raw_body: bytes, headers, *, now: float | None = None) -> None:
    secret = get_settings().abliner_webhook_secret.get_secret_value()
    if not secret:
        raise Rejected(503, "webhook_not_configured")
    if len(raw_body) > MAX_BODY_BYTES:
        raise Rejected(413, "payload_too_large")
    timestamp = _header(headers, "x-webhook-timestamp").strip()
    if not timestamp.isdigit() or len(timestamp) > 12:
        raise Rejected(401, "invalid_timestamp")
    if abs((now if now is not None else time.time()) - int(timestamp)) > TOLERANCE_SECONDS:
        raise Rejected(401, "stale_timestamp")
    supplied = _header(headers, "x-webhook-signature").strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied[7:]
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw_body, hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(expected.encode("ascii"), supplied.lower().encode("latin-1", "replace")):
        raise Rejected(401, "invalid_signature")


def _int(value) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _remote(payload: dict) -> tuple[str | None, settlement.Remote]:
    event = str(payload.get("event") or "")[:60] or None
    if event == "checkout.paid":  # documented only in Abliner's Checkout section; accepted, never relied on
        return event, settlement.Remote(status="completed", tx_id=str(payload.get("id") or "")[:80] or None,
                                        amount=_int(payload.get("amount")), currency=payload.get("currency"),
                                        reference=str(payload.get("reference") or "")[:80] or None,
                                        completed_at=_time(payload.get("paid_at")), event=event)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    remote_status = str(data.get("status") or ("completed" if event == "transaction.completed" else
                                               "failed" if event == "transaction.failed" else ""))[:30]
    return event, settlement.Remote(
        status=remote_status, tx_id=str(data.get("id") or "")[:80] or None, amount=_int(data.get("amount")),
        currency=data.get("currency"), reference=str(data.get("customer_reference") or "")[:80] or None,
        provider_reference=str(data.get("provider_reference") or "")[:120] or None,
        completed_at=_time(data.get("completed_at")), event=event)


def _find(db: Session, remote: settlement.Remote) -> tuple[PaymentIntent | None, list[PaymentIntent]]:
    """The intent by our reference (unique), else by Abliner's transaction id. Returns (intent, others): `others`
    are further intents carrying the same transaction id (security review L4), which must never happen; then
    nothing is settled and every one of them goes to review."""
    if remote.reference:
        intent = db.query(PaymentIntent).filter(PaymentIntent.reference == remote.reference).one_or_none()
        if intent is not None:
            return intent, []
    if remote.tx_id:
        rows = (db.query(PaymentIntent).filter(PaymentIntent.abliner_tx_id == remote.tx_id)
                .order_by(PaymentIntent.created_at, PaymentIntent.id).limit(10).all())
        if rows:
            return rows[0], rows[1:]
    return None, []


def _retryable(db: Session, webhook_id: str) -> AblinerWebhookEvent | None:
    """The stored event, locked, if its settlement failed (outcome "error"): Abliner's retry settles it. Any other
    stored outcome is a duplicate. FOR UPDATE serialises concurrent retries; once one has committed a new outcome,
    the row no longer matches for the next, which is then a duplicate (settlement is also idempotent per intent)."""
    return (db.query(AblinerWebhookEvent)
            .filter(AblinerWebhookEvent.webhook_id == webhook_id, AblinerWebhookEvent.outcome == "error")
            .with_for_update().one_or_none())


def process(db: Session, raw_body: bytes, headers) -> Outcome:
    """Verify, dedupe, settle. Commits. Raises Rejected for an unverifiable request: nothing from it is stored,
    only the rejection code and time on the Integrations status."""
    try:
        verify(raw_body, headers)
    except Rejected as exc:
        if integration_status.unverified_error(db, "abliner", exc.code):  # L3: throttled, never hides a real error
            db.commit()
        raise
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise Rejected(400, "invalid_json") from None
    if not isinstance(payload, dict):
        raise Rejected(400, "invalid_json")
    webhook_id = (_header(headers, "x-webhook-id").strip() or str(payload.get("id") or "").strip())[:120]
    if not webhook_id:
        raise Rejected(400, "missing_webhook_id")
    event, remote = _remote(payload)
    record = AblinerWebhookEvent(webhook_id=webhook_id, event=event, abliner_tx_id=remote.tx_id,
                                 customer_reference=remote.reference, remote_status=remote.status or None,
                                 amount=remote.amount, currency=(remote.currency or None) and str(remote.currency)[:3])
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError:
        db.rollback()
        record = _retryable(db, webhook_id)
        if record is None:
            logger.info("Abliner webhook duplicate webhook=%s", webhook_id)
            return Outcome("duplicate", "duplicate")
        logger.info("Abliner webhook redelivered after a settlement error webhook=%s", webhook_id)
    integration_status.webhook(db, "abliner", event)
    intent, others = _find(db, remote)
    if intent is None:
        record.outcome = "ignored"
        db.commit()
        logger.info("Abliner webhook without a matching payment webhook=%s abliner=%s", webhook_id, remote.tx_id)
        return Outcome("ok", "ignored")
    record.intent_id = intent.id
    try:
        if others:  # L4: one Abliner transaction, several payments: a person decides, nothing is credited
            why = f"Abliner transaction id is shared by {len(others) + 1} payments."
            outcome = "review"
            for item in [intent, *others]:
                settlement.flag(db, item.id, why, remote)
        else:
            outcome = settlement.apply(db, intent.id, remote)
    except Exception:
        # Security review round 4, item 1: keep the event as "error" (retryable, see _retryable) and answer 503, so
        # Abliner's retries (about 2 s and 5 s later) settle it; reconciliation remains the safety net after that.
        db.rollback()
        db.merge(AblinerWebhookEvent(webhook_id=webhook_id, event=event, abliner_tx_id=remote.tx_id,
                                     customer_reference=remote.reference, remote_status=remote.status or None,
                                     amount=remote.amount, currency=(remote.currency or None) and str(remote.currency)[:3],
                                     intent_id=intent.id,
                                     outcome="error"))
        integration_status.error(db, "abliner", "settlement_error")
        db.commit()
        logger.exception("Abliner webhook settlement error webhook=%s intent=%s", webhook_id, intent.id)
        return Outcome("retry", "error")
    record.outcome = outcome
    db.commit()
    logger.info("Abliner webhook processed webhook=%s intent=%s outcome=%s", webhook_id, intent.id, outcome)
    return Outcome("ok", outcome)
