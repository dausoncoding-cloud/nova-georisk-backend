"""Customer view of the organisation's subscriptions and credits (every active member may read).

Organisation-scoped: only the session's organisation is ever read. Payments and admin actions are not
here (owners/admins and the NOVA ARI console, later milestones).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.entitlements import require_active_membership
from app.core.http import PublicAPIError
from app.core.security import RequestContext, get_request_context, verify_internal_secret
from app.db.session import get_db
from app.models.billing import CreditLedgerEntry
from app.models.platform import BillingPlan, OrganizationSubscription
from app.schemas.billing import (BillingSummaryResponse, CreditSummary, LedgerEntryResponse, LedgerPage,
                                 SubscriptionSummary)
from app.services.billing import catalogue, ledger
from app.services.billing import submission as billing

router = APIRouter(prefix="/billing", tags=["Billing"], dependencies=[Depends(verify_internal_secret)])

STATUS_LABELS = {"active": "Active", "trial": "Trial", "suspended": "Suspended", "expired": "Expired",
                 "canceled": "Cancelled", "pending": "Pending"}


def _require_member(db: Session, context: RequestContext) -> None:
    if context.is_service:
        raise PublicAPIError(403, "organization_context_required", "An organisation session is required.")
    require_active_membership(db, context)


def _summary(db: Session, subscription: OrganizationSubscription) -> SubscriptionSummary:
    plan = db.get(BillingPlan, subscription.plan_key) if subscription.plan_key else None
    usage = ledger.usage(db, subscription)
    code = billing.block_code(subscription)
    if code is None and usage.remaining <= 0:
        code = "credits_exhausted"
    message = billing.NO_CREDITS if code == "credits_exhausted" else billing.STATUS_MESSAGES.get(code)
    return SubscriptionSummary(
        id=subscription.id, family=subscription.family, plan_key=subscription.plan_key,
        plan_name=plan.name if plan else None, status=subscription.status.value,
        status_label=STATUS_LABELS[subscription.status.value], starts_at=subscription.starts_at,
        ends_at=subscription.ends_at, engines=catalogue.family_engines(subscription.family),
        credits=CreditSummary(period=usage.period, granted=usage.granted, top_ups=usage.top_ups, used=usage.used,
                              remaining=usage.remaining, available=usage.available,
                              used_percent=usage.used_percent, level=usage.level),
        can_submit=code is None or not billing.enforcement_enabled(),
        block_code=code, block_message=message,
    )


@router.get("/summary", response_model=BillingSummaryResponse)
def get_billing_summary(
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> BillingSummaryResponse:
    _require_member(db, context)
    ids = [row.id for row in db.query(OrganizationSubscription.id).filter(
        OrganizationSubscription.organization_id == context.organization_id,
        OrganizationSubscription.family.isnot(None)).order_by(OrganizationSubscription.family)]
    items = []
    for subscription_id in ids:
        # Lazily bring the subscription to this billing month (idempotent grant/expiry) before reading it.
        subscription = ledger.lock_subscription(db, subscription_id)
        ledger.ensure_period(db, subscription)
        db.commit()
        items.append(_summary(db, db.get(OrganizationSubscription, subscription_id)))
    return BillingSummaryResponse(enforcement_enabled=billing.enforcement_enabled(), subscriptions=items)


@router.get("/ledger", response_model=LedgerPage)
def get_ledger(
    family: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> LedgerPage:
    _require_member(db, context)
    query = db.query(CreditLedgerEntry).filter(CreditLedgerEntry.organization_id == context.organization_id)
    if family is not None:
        query = query.join(OrganizationSubscription,
                           OrganizationSubscription.id == CreditLedgerEntry.subscription_id).filter(
            OrganizationSubscription.family == family)
    total = query.count()
    rows = query.order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id).offset(offset).limit(limit).all()
    return LedgerPage(items=[LedgerEntryResponse(
        id=row.id, created_at=row.created_at, period=row.period, kind=row.kind, bucket=row.bucket, amount=row.amount,
        balance_after=row.balance_after, task_id=row.task_id, reason=row.reason) for row in rows],
        total=total, limit=limit, offset=offset)
