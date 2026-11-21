"""Mobile Money payments in "review" (amount, currency or reference mismatch, or a "completed" after the intent
expired or failed): NOVA ARI sees them on the Payments page and closes each with a reason (audited). Credits are
never added here: an admin who decides the customer paid records the payment in the console first."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.abliner import PaymentIntent
from app.services.billing import audit

RESOLUTIONS = ("credited_manually", "no_action")


class ReviewError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def open_reviews(db: Session):
    return db.query(PaymentIntent).filter(PaymentIntent.status == "review", PaymentIntent.resolved_at.is_(None))


def resolve(db: Session, intent_id: uuid.UUID, *, resolution: str, reason: str, actor: audit.Actor) -> PaymentIntent:
    reason = audit.require_reason(reason)
    if resolution not in RESOLUTIONS:
        raise ReviewError("resolution_invalid", "Choose credited_manually or no_action.", 422)
    intent = (db.query(PaymentIntent).filter(PaymentIntent.id == intent_id).populate_existing()
              .with_for_update().one_or_none())
    if intent is None:
        raise ReviewError("payment_not_found", "Payment not found.", 404)
    if intent.status != "review" or intent.resolved_at is not None:
        raise ReviewError("not_in_review", "This payment is not waiting for review.")
    intent.resolved_at, intent.resolved_by_user_id, intent.resolution = datetime.now(timezone.utc), actor.user_id, resolution
    db.flush()
    audit.record(db, actor, "abliner.review_resolved", reason=reason, organization_id=intent.organization_id,
                 target_type="payment_intent", target_id=intent.id, previous={"status": "review"},
                 current={"resolution": resolution, "abliner_tx_id": intent.abliner_tx_id})
    return intent
