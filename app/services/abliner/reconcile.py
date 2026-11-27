"""Reconciliation (plan §5): the safety net for webhooks (Abliner retries them only twice).

Open intents (created, pending, pending_unknown) older than ABLINER_RECONCILE_MIN_AGE_MINUTES (3) are looked up
at Abliner by our reference (customer_reference), falling back to the intent's Idempotency-Key, at most 50 per
run (Abliner allows 120 reads a minute):
- the transaction used is the one with our reference, else the one whose id is the intent's abliner_tx_id; any
  other transaction Abliner returns is handed to settlement, which sends a reported result to review and never
  credits it (security review M3: a reference-less deposit of a common amount is not this payment);
- completed -> settle (settlement.apply; a late result for an expired intent goes to review there);
- failed -> failed;
- no result (pending, unknown, or not found) and older than ABLINER_INTENT_EXPIRY_MINUTES (30) -> expired.
An Abliner error leaves the intent alone for the next run (until the expiry window ends). Each intent is
committed on its own, so one failure never blocks the others. Dry run unless apply=True.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.abliner import OPEN_STATUSES, PaymentIntent
from app.services.abliner import settlement
from app.services.abliner.client import AblinerClient, AblinerError
from app.services.abliner.webhooks import _int, _time
from app.services.integrations import status as integration_status

logger = logging.getLogger(__name__)
BATCH = 50


@dataclass
class Report:
    mode: str
    checked: int = 0
    counts: dict = field(default_factory=dict)

    def add(self, outcome: str) -> None:
        self.counts[outcome] = self.counts.get(outcome, 0) + 1


def _pick(intent: PaymentIntent, items: list[dict]) -> dict | None:
    """M3: our own transaction first (our reference, then our Abliner id); otherwise whatever came back, which
    settlement will refuse to credit."""
    if not items:
        return None
    for item in items:
        if item.get("customer_reference") == intent.reference:
            return item
    if intent.abliner_tx_id:
        for item in items:
            if not item.get("customer_reference") and str(item.get("id") or "") == intent.abliner_tx_id:
                return item
    return items[0]


def _lookup(client: AblinerClient, intent: PaymentIntent) -> settlement.Remote | None:
    items = client.transactions(customer_reference=intent.reference)
    if not items:
        items = client.transactions(idempotency_key=intent.idempotency_key)
    item = _pick(intent, items)
    if item is None:
        return None
    return settlement.Remote(
        status=str(item.get("status") or "")[:30], tx_id=str(item.get("id") or "")[:80] or None,
        amount=_int(item.get("amount")), currency=item.get("currency"),
        reference=str(item.get("customer_reference") or "")[:80] or None,
        provider_reference=str(item.get("provider_reference") or "")[:120] or None,
        completed_at=_time(item.get("completed_at")), source="reconciliation")


def run(db: Session, client: AblinerClient, *, apply: bool, now: datetime | None = None) -> Report:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    min_age = timedelta(minutes=settings.abliner_reconcile_min_age_minutes)
    expiry = timedelta(minutes=settings.abliner_intent_expiry_minutes)
    report = Report(mode="apply" if apply else "dry-run")
    ids = [row.id for row in db.query(PaymentIntent.id).filter(PaymentIntent.status.in_(OPEN_STATUSES),
                                                               PaymentIntent.created_at <= now - min_age)
           .order_by(PaymentIntent.created_at).limit(BATCH)]
    for intent_id in ids:
        intent = db.get(PaymentIntent, intent_id)
        report.checked += 1
        expired = intent.created_at <= now - expiry
        try:
            remote = _lookup(client, intent)
            integration_status.success(db, "abliner")
        except AblinerError as exc:
            integration_status.error(db, "abliner", f"reconcile_{exc.code}")
            remote = None
            if not expired:
                report.add("error")
                db.commit() if apply else db.rollback()
                continue
        status = (remote.status if remote else "").lower()
        if status in {"completed", "failed"}:
            outcome = settlement.apply(db, intent.id, remote) if apply else f"would_{status}"
        elif expired:
            outcome = settlement.expire(db, intent.id) if apply else "would_expire"
        else:
            outcome = "unchanged"
        report.add(outcome)
        if apply:
            db.commit()
            logger.info("Abliner reconcile intent=%s abliner=%s outcome=%s", intent.id, intent.abliner_tx_id, outcome)
        else:
            db.rollback()
    return report
