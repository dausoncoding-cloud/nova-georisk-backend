"""Customer requests to NOVA ARI from "My subscription": a top-up pack or a plan upgrade. No payment is
taken in the app; NOVA ARI sends payment details to the owner and records the payment or plan change in
the console, then closes the request with an outcome and a reason."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform import BillingPlan, OrganizationSubscription
from app.models.platform_admin import SubscriptionRequest
from app.services.billing import audit, catalogue, ledger


class RequestError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Created:
    request: SubscriptionRequest
    existing: bool


def create(db: Session, *, organization_id: uuid.UUID, user_id: uuid.UUID, subscription_id: uuid.UUID, kind: str,
           plan_key: str | None = None, note: str | None = None, storage_gb: int | None = None) -> Created:
    subscription = db.get(OrganizationSubscription, subscription_id)
    if subscription is None or subscription.organization_id != organization_id or subscription.family is None:
        raise RequestError("subscription_not_found", "Subscription not found.", 404)
    credits = None
    if kind == "top_up":
        if not ledger.is_current(subscription):  # Q7
            raise RequestError("plan_not_active", "Renew your plan first: top-up credits can only be used with an active plan.", 409)
        price = catalogue.current_price(db, subscription.plan_key) if subscription.plan_key else None
        if price is None or price.top_up_credit_price is None:
            raise RequestError("top_up_unavailable", "Top-ups are not offered for this plan yet. Contact NOVA ARI.", 409)
        credits, plan_key = catalogue.TOP_UP_PACK_CREDITS, None
    elif kind == "storage":  # Q5b: extra storage, priced by NOVA ARI until a price per GB is set (plans file)
        if not storage_gb or not 1 <= storage_gb <= 10000:
            raise RequestError("storage_gb_invalid", "Ask for between 1 and 10,000 GB.")
        plan_key = None
    elif kind == "upgrade":
        plan = db.get(BillingPlan, plan_key) if plan_key else None
        if (plan is None or plan.family != subscription.family or plan.is_internal or plan.status != "active"
                or plan.key == subscription.plan_key):
            raise RequestError("plan_invalid", "Choose another plan for this system.")
    else:
        raise RequestError("kind_invalid", "Unknown request.")
    open_request = _open_request(db, subscription.id, kind)
    if open_request is not None:
        return Created(open_request, existing=True)
    request = SubscriptionRequest(organization_id=organization_id, subscription_id=subscription.id, kind=kind,
                                  plan_key=plan_key, credits=credits, requested_by_user_id=user_id,
                                  storage_gb=storage_gb if kind == "storage" else None,
                                  note=(note or "").strip()[:1000] or None, status="open")
    try:  # two parallel requests: the unique open-request index decides, the loser gets the winner's request
        with db.begin_nested():
            db.add(request)
            db.flush()
    except IntegrityError:
        winner = _open_request(db, subscription.id, kind)
        if winner is None:
            raise
        return Created(winner, existing=True)
    return Created(request, existing=False)


def _open_request(db: Session, subscription_id: uuid.UUID, kind: str) -> SubscriptionRequest | None:
    return (db.query(SubscriptionRequest)
            .filter(SubscriptionRequest.subscription_id == subscription_id, SubscriptionRequest.kind == kind,
                    SubscriptionRequest.status == "open").populate_existing().one_or_none())


def close(db: Session, request_id: uuid.UUID, *, outcome: str, reason: str, actor: audit.Actor) -> SubscriptionRequest:
    reason = audit.require_reason(reason)
    if outcome not in {"done", "declined"}:
        raise RequestError("outcome_invalid", "The outcome is 'done' or 'declined'.")
    request = db.query(SubscriptionRequest).filter(SubscriptionRequest.id == request_id).with_for_update().one_or_none()
    if request is None:
        raise RequestError("request_not_found", "Request not found.", 404)
    if request.status != "open":
        raise RequestError("request_closed", "This request is already closed.", 409)
    request.status, request.closed_at = outcome, datetime.now(timezone.utc)
    request.closed_by_user_id, request.close_reason = actor.user_id, reason
    db.flush()
    audit.record(db, actor, "request.close", reason=reason, organization_id=request.organization_id,
                 target_type="subscription_request", target_id=request.id,
                 previous={"status": "open", "kind": request.kind},
                 current={"status": outcome, "plan_key": request.plan_key, "credits": request.credits})
    return request
