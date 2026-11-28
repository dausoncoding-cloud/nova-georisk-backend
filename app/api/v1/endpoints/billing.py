"""Customer view of the organisation's subscriptions and credits (every active member may read).

Organisation-scoped: only the session's organisation is ever read. Payments are visible to owners and
admins only. Nothing here writes billing data: payments, top-ups and status changes are NOVA ARI actions.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.entitlements import require_active_membership
from app.core.http import PublicAPIError
from app.core.security import OrganizationRole, RequestContext, get_request_context, verify_internal_secret
from app.db.session import get_db
from app.models.aoi import AOI
from app.models.billing import CreditLedgerEntry, Payment
from app.models.platform import BillingPlan, OrganizationSubscription
from app.models.project import Project
from app.models.task import Task
from app.schemas.billing import (Allowance, BillingSummaryResponse, CreditSummary, LedgerEntryResponse, LedgerPage,
                                 PaymentPage, PaymentResponse, PlanCatalogueResponse, PlanLimits, PlanOption,
                                 SubscriptionRequestCreate, SubscriptionRequestResponse, SubscriptionSummary,
                                 TopUpOffer)
from app.models.platform_admin import SubscriptionRequest
from app.services.billing import requests as billing_requests
from app.services.billing import catalogue, ledger, limits
from app.services.billing.labels import customer_label
from app.services.billing import submission as billing

router = APIRouter(prefix="/billing", tags=["Billing"], dependencies=[Depends(verify_internal_secret)])

STATUS_LABELS = {"active": "Active", "trial": "Trial", "suspended": "Suspended", "expired": "Expired",
                 "canceled": "Cancelled", "pending": "Pending"}


def _require_member(db: Session, context: RequestContext):
    if context.is_service:
        raise PublicAPIError(403, "organization_context_required", "An organisation session is required.")
    return require_active_membership(db, context)


def _allowance(value: limits.Allowance) -> Allowance:
    return Allowance(used=value.used, limit=value.limit, level=value.level)


def _summary(db: Session, subscription: OrganizationSubscription, seats_used: int,
             storage_full: bool) -> SubscriptionSummary:
    plan = db.get(BillingPlan, subscription.plan_key) if subscription.plan_key else None
    unlimited = ledger.has_unlimited_credits(db, subscription)
    usage = ledger.usage(db, subscription)
    code = billing.block_code(subscription)
    if code is None and storage_full:
        code = "storage_full"
    if code is None and not unlimited and usage.remaining <= 0:
        code = "credits_exhausted"
    message = {"credits_exhausted": billing.NO_CREDITS,
               "storage_full": limits.STORAGE_FULL_MESSAGE}.get(code) or billing.STATUS_MESSAGES.get(code)
    price = catalogue.current_price(db, subscription.plan_key) if subscription.plan_key else None
    top_up = None
    if price is not None and price.top_up_credit_price is not None:
        top_up = TopUpOffer(credits=catalogue.TOP_UP_PACK_CREDITS, currency=price.currency,
                            price=catalogue.TOP_UP_PACK_CREDITS * price.top_up_credit_price)
    return SubscriptionSummary(
        id=subscription.id, family=subscription.family, plan_key=subscription.plan_key,
        plan_name=plan.name if plan else None, is_internal=bool(plan and plan.is_internal),
        status=subscription.status.value,
        status_label=STATUS_LABELS[subscription.status.value], starts_at=subscription.starts_at,
        ends_at=subscription.ends_at, engines=catalogue.family_engines(subscription.family),
        currency=price.currency if price else "TZS", monthly_price=price.monthly_price if price else None,
        limits=PlanLimits(**ledger.effective_limits(db, subscription)), seats_used=seats_used,
        renews_on=ledger.renews_on(subscription), warning_levels=list(ledger.WARNING_LEVELS), top_up=top_up,
        credits=CreditSummary(period=usage.period, granted=usage.granted, top_ups=usage.top_ups, used=usage.used,
                              remaining=usage.remaining, available=usage.available,
                              used_percent=0.0 if unlimited else usage.used_percent,
                              level=None if unlimited else usage.level, unlimited=unlimited),
        can_submit=code is None or not billing.enforcement_enabled(),
        block_code=code, block_message=message,
    )


@router.get("/summary", response_model=BillingSummaryResponse)
def get_billing_summary(
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> BillingSummaryResponse:
    """Write on GET, by design and idempotent (independent review 6): before reading, each subscription is
    brought to the current billing month, which writes the month's grant (and the previous month's expiry)
    at most once, under the subscription row lock, keyed grant:<subscription>:<YYYY-MM>. Repeating the GET,
    or a cross-site GET, can only cause that same single write earlier than the first analysis would."""
    _require_member(db, context)
    ids = [row.id for row in db.query(OrganizationSubscription.id).filter(
        OrganizationSubscription.organization_id == context.organization_id,
        OrganizationSubscription.family.isnot(None)).order_by(OrganizationSubscription.family)]
    for subscription_id in ids:
        # Lazily bring the subscription to this billing month (idempotent grant/expiry) before reading it.
        subscription = ledger.lock_subscription(db, subscription_id)
        ledger.ensure_period(db, subscription)
        db.commit()
    seats = limits.seats(db, context.organization_id)
    storage = limits.storage(db, context.organization_id)
    storage_full = limits.storage_blocks_submission(db, context.organization_id)
    items = [_summary(db, db.get(OrganizationSubscription, subscription_id), seats.used, storage_full)
             for subscription_id in ids]
    return BillingSummaryResponse(enforcement_enabled=billing.enforcement_enabled(), subscriptions=items,
                                  seats=_allowance(seats), storage=_allowance(storage),
                                  storage_blocks_at_limit=get_settings().billing_storage_block_at_limit)


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
    # Names for the activity column, read only through this organisation's own projects.
    task_ids = {row.task_id for row in rows if row.task_id}
    names = {
        task_id: (project_name, aoi_name)
        for task_id, project_name, aoi_name in db.query(Task.id, Project.name, AOI.name)
        .join(Project, Project.id == Task.project_id).outerjoin(AOI, AOI.id == Task.aoi_id)
        .filter(Task.id.in_(task_ids), Project.organization_id == context.organization_id)
    } if task_ids else {}
    plan_names = {plan.key: plan.name for plan in db.query(BillingPlan)}
    items = []
    for row in rows:
        project_name, aoi_name = names.get(row.task_id, (None, None))
        plan_key = (row.metadata_json or {}).get("plan_key") if row.kind == "monthly_grant" else None
        items.append(LedgerEntryResponse(
            id=row.id, created_at=row.created_at, period=row.period, kind=row.kind, bucket=row.bucket,
            amount=row.amount, balance_after=row.balance_after, task_id=row.task_id, label=customer_label(row),
            project_name=project_name, aoi_name=aoi_name, plan_name=plan_names.get(plan_key)))
    return LedgerPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/plans", response_model=PlanCatalogueResponse)
def get_plan_catalogue(
    family: str = Query(..., pattern="^(frris_wrris|megis)$"),
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> PlanCatalogueResponse:
    """The plan table on "My subscription" (prices are public list prices, not organisation data)."""
    _require_member(db, context)
    plans = db.query(BillingPlan).filter(BillingPlan.family == family, BillingPlan.status == "active",
                                         BillingPlan.is_internal.is_(False)) \
        .order_by(BillingPlan.sort_order).all()
    options = []
    for plan in plans:
        price = catalogue.current_price(db, plan.key)
        options.append(PlanOption(
            key=plan.key, family=family, name=plan.name, is_custom=plan.is_custom,
            currency=price.currency if price else "TZS", monthly_price=price.monthly_price if price else None,
            limits=PlanLimits(seat_limit=plan.seat_limit, monthly_credits=plan.monthly_credits,
                              storage_bytes=plan.storage_bytes, session_limit=plan.session_limit)))
    return PlanCatalogueResponse(family=family, plans=options)


@router.get("/payments", response_model=PaymentPage)
def get_payments(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> PaymentPage:
    """Payments NOVA ARI recorded for this organisation (owners and admins only). Admin notes are not shown."""
    membership = _require_member(db, context)
    if membership.role.value not in {OrganizationRole.OWNER.value, OrganizationRole.ADMIN.value}:
        raise PublicAPIError(403, "billing_role_required", "Only organisation owners and admins can see payments.")
    # Security review L5: the operator's gateway test (purpose "test") and its reversal are not the customer's.
    test_ids = db.query(Payment.id).filter(Payment.organization_id == context.organization_id, Payment.purpose == "test")
    query = db.query(Payment).filter(Payment.organization_id == context.organization_id, Payment.purpose != "test",
                                     or_(Payment.reverses_payment_id.is_(None), Payment.reverses_payment_id.notin_(test_ids)))
    total = query.count()
    rows = query.order_by(Payment.paid_on.desc(), Payment.created_at.desc(), Payment.id).offset(offset).limit(limit).all()
    reversed_ids = {row.reverses_payment_id for row in db.query(Payment.reverses_payment_id).filter(
        Payment.organization_id == context.organization_id, Payment.reverses_payment_id.isnot(None))}
    families = dict(db.query(OrganizationSubscription.id, OrganizationSubscription.family).filter(
        OrganizationSubscription.organization_id == context.organization_id))
    return PaymentPage(items=[PaymentResponse(
        id=row.id, created_at=row.created_at, paid_on=row.paid_on, family=families.get(row.subscription_id),
        purpose=row.purpose, amount=row.amount, currency=row.currency, method=row.method, reference=row.reference,
        credits=row.credits, covers_from=row.covers_from, covers_until=row.covers_until,
        reverses_payment_id=row.reverses_payment_id, reversed=row.id in reversed_ids) for row in rows],
        total=total, limit=limit, offset=offset)


def _require_billing_role(db: Session, context: RequestContext):
    membership = _require_member(db, context)
    if membership.role.value not in {OrganizationRole.OWNER.value, OrganizationRole.ADMIN.value}:
        raise PublicAPIError(403, "billing_role_required",
                             "Only organisation owners and admins can request top-ups or plan changes.")
    return membership


def _request_view(db: Session, row: SubscriptionRequest, existing: bool = False) -> SubscriptionRequestResponse:
    plan = db.get(BillingPlan, row.plan_key) if row.plan_key else None
    return SubscriptionRequestResponse(
        id=row.id, subscription_id=row.subscription_id, kind=row.kind, plan_key=row.plan_key,
        plan_name=plan.name if plan else None, credits=row.credits, status=row.status, created_at=row.created_at,
        closed_at=row.closed_at, existing=existing)


@router.post("/requests", response_model=SubscriptionRequestResponse, status_code=201)
def create_request(
    body: SubscriptionRequestCreate,
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> SubscriptionRequestResponse:
    """"Request top-up" / "Request upgrade": sends a request to NOVA ARI (no payment in the app). Asking again
    while one is open returns the open request."""
    _require_billing_role(db, context)
    try:
        created = billing_requests.create(db, organization_id=context.organization_id, user_id=context.user_id,
                                          subscription_id=body.subscription_id, kind=body.kind,
                                          plan_key=body.plan_key, note=body.note)
    except billing_requests.RequestError as exc:
        db.rollback()
        raise PublicAPIError(exc.status, exc.code, exc.message) from exc
    db.commit()
    return _request_view(db, created.request, created.existing)


@router.get("/requests", response_model=list[SubscriptionRequestResponse])
def list_requests(
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> list[SubscriptionRequestResponse]:
    """This organisation's recent requests (owners and admins)."""
    _require_billing_role(db, context)
    rows = (db.query(SubscriptionRequest).filter(SubscriptionRequest.organization_id == context.organization_id)
            .order_by(SubscriptionRequest.created_at.desc()).limit(20).all())
    return [_request_view(db, row) for row in rows]
