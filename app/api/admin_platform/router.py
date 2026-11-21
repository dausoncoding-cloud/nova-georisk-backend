"""NOVA ARI console API (plan sections 7-8; board 14 `NOVA-ARI_Admin_dashboard.png`).

Every route: internal secret (BFF only) + `require_platform_admin` (live grant in the database, checked
per request). Every write: a reason, and a `platform_audit` row in the same transaction. Payment and
credit writes also take an `Idempotency-Key`, so a repeated click records once. Cross-organisation
login history is the one read that is audited too, so it is a POST (CSRF-protected). Three GETs also write,
idempotently: reading customers (here) and GET /api/v1/billing/summary (customers) bring each subscription
to the current month (the monthly grant, once per month), and reading a customer flushes the usage buffer.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.endpoints.billing import _summary as subscription_summary
from app.core.config import get_settings
from app.core.http import PublicAPIError
from app.core.security import verify_internal_secret
from app.db.session import get_db
from app.models.billing import CreditLedgerEntry, Payment, PlatformAudit
from app.models.identity import Organization, OrganizationMembership, User
from app.models.platform import BillingPlan, OrganizationSubscription
from app.models.platform_admin import SecurityAlert
from app.models.sessions import UserSession
from app.schemas.billing import LedgerEntryResponse, LedgerPage, PaymentResponse, PlanLimits
from app.schemas.platform_admin import (AddCustomerRequest, AddSubscriptionRequest, AdjustCreditsRequest, AdminAccess,
                                        AdminLoginEntry, AdminLoginPage, AdminPaymentPage, AdminPaymentResponse,
                                        AdminPlan, AuditEntry, AuditPage, CreditsChanged, CustomerCreated,
                                        CustomerDetail, CustomerPage, CustomerRowResponse, EndSessionsRequest,
                                        EndSessionsResponse, GrantCreditsRequest, LimitChangeRequest, MemberResponse,
                                        OverviewTiles, PaymentRecorded, PlanChangeRequest, PriceChangeRequest,
                                        ReasonRequest, RecordPaymentRequest, SecurityAlertPage, SecurityAlertResponse,
                                        StatusChangeRequest, UsageThisPeriod, AdminRequest, AdminRequestPage,
                                        CloseRequest)
from app.models.platform_admin import SubscriptionRequest
from app.services.billing import requests as billing_requests
from app.services.billing import audit, backfill, ledger, limits, payments, statuses
from app.services.billing.submission import validate_key
from app.services.platform_admin import actions, overview
from app.services.platform_admin.access import AdminContext, require_platform_admin
from app.services.sessions.tracking import SessionTracker, get_session_tracker
from app.services.usage import counters

router = APIRouter(prefix="/platform-admin", tags=["NOVA ARI administration"],
                   dependencies=[Depends(verify_internal_secret)])

ATTRIBUTION = "IP geolocation by DB-IP"


@contextmanager
def _errors(db: Session):
    """Domain errors -> stable 4xx; anything else rolls back and propagates."""
    try:
        yield
    except (payments.PaymentError, actions.ActionError) as exc:
        db.rollback()
        raise PublicAPIError(exc.status, exc.code, exc.message) from exc
    except audit.ReasonRequired as exc:
        db.rollback()
        raise PublicAPIError(422, "reason_required", str(exc)) from exc
    except statuses.StatusError as exc:
        db.rollback()
        raise PublicAPIError(409, "status_unchanged", str(exc)) from exc
    except ledger.LedgerError as exc:
        db.rollback()
        raise PublicAPIError(404 if "not found" in str(exc).lower() else 409, "ledger_refused", str(exc)) from exc
    except backfill.BackfillError as exc:
        db.rollback()
        raise PublicAPIError(422, "invalid_request", str(exc)) from exc
    except billing_requests.RequestError as exc:
        db.rollback()
        raise PublicAPIError(exc.status, exc.code, exc.message) from exc


def _overrides(value) -> dict | None:
    """Only the override fields the admin sent (null clears one)."""
    return value.model_dump(exclude_unset=True) if value is not None else None


def _key(value: str | None) -> str:
    """The same rule as analysis submission (A1): 8-128 characters of [A-Za-z0-9_-:.] (independent review 1)."""
    key = validate_key(value)
    if key is None:
        raise PublicAPIError(422, "idempotency_key_required", "Send an Idempotency-Key header (8-128 characters).")
    return f"admin:{key}"


def _organization(db: Session, organization_id: uuid.UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise PublicAPIError(404, "organization_not_found", "Customer not found.")
    return organization


def _subscription(db: Session, subscription_id: uuid.UUID) -> OrganizationSubscription:
    subscription = db.get(OrganizationSubscription, subscription_id)
    if subscription is None or subscription.family is None:
        raise PublicAPIError(404, "subscription_not_found", "Subscription not found.")
    return subscription


def _row(row: overview.CustomerRow) -> CustomerRowResponse:
    return CustomerRowResponse(**row.__dict__)


def _payment(row: Payment, family: str | None, reversed_ids: set) -> PaymentResponse:
    return PaymentResponse(
        id=row.id, created_at=row.created_at, paid_on=row.paid_on, family=family, purpose=row.purpose,
        amount=row.amount, currency=row.currency, method=row.method, reference=row.reference, credits=row.credits,
        covers_from=row.covers_from, covers_until=row.covers_until, reverses_payment_id=row.reverses_payment_id,
        reversed=row.id in reversed_ids)


def _flush_usage(db: Session) -> None:
    try:
        counters.flush(db)
    except Exception:
        db.rollback()


# --- who, tiles, customers --------------------------------------------------------------------------

@router.get("/access", response_model=AdminAccess)
def access(admin: AdminContext = Depends(require_platform_admin)) -> AdminAccess:
    return AdminAccess(display_name=admin.display_name, email=admin.email, organization_name=admin.organization_name)


@router.get("/overview", response_model=OverviewTiles)
def get_overview(db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin)) -> OverviewTiles:
    return OverviewTiles(**overview.tiles(db, overview.customer_rows(db)))


@router.get("/customers", response_model=CustomerPage)
def list_customers(
    q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(active|trial|suspended|expired|canceled|pending|none)$"),
    family: str | None = Query(None, pattern="^(frris_wrris|megis)$"),
    flag: str | None = Query(None, pattern="^(" + "|".join(overview.FLAGS) + ")$"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin),
) -> CustomerPage:
    rows = overview.filter_rows(db, overview.customer_rows(db), q=q, status=status, family=family, flag=flag)
    return CustomerPage(items=[_row(row) for row in rows[offset:offset + limit]], total=len(rows), limit=limit,
                        offset=offset)


@router.post("/customers", response_model=CustomerCreated, status_code=201)
def add_customer(body: AddCustomerRequest, db: Session = Depends(get_db),
                 admin: AdminContext = Depends(require_platform_admin)) -> CustomerCreated:
    with _errors(db):
        organization, subscription, owner = actions.add_customer(
            db, name=body.name, slug=body.slug, family=body.family, plan_key=body.plan_key, reason=body.reason,
            actor=admin.actor, starts_at=body.starts_at, ends_at=body.ends_at, overrides=_overrides(body.overrides),
            owner_issuer=body.owner_issuer, owner_subject=body.owner_subject, owner_email=body.owner_email,
            owner_name=body.owner_name)
        db.commit()
    return CustomerCreated(organization_id=organization.id, subscription_id=subscription.id,
                           owner_user_id=owner.id if owner else None)


@router.get("/customers/{organization_id}", response_model=CustomerDetail)
def customer_detail(organization_id: uuid.UUID, db: Session = Depends(get_db),
                    admin: AdminContext = Depends(require_platform_admin)) -> CustomerDetail:
    organization = _organization(db, organization_id)
    _flush_usage(db)
    rows = [row for row in overview.customer_rows(db) if row.organization_id == organization_id]
    storage_full = limits.storage_blocks_submission(db, organization_id)
    seats_used = limits.seats_used(db, organization_id)
    summaries = [subscription_summary(db, subscription, seats_used, storage_full)
                 for subscription in limits.subscriptions(db, organization_id)]
    now = datetime.now(timezone.utc)
    members = []
    for membership, user in (db.query(OrganizationMembership, User).join(User, User.id == OrganizationMembership.user_id)
                             .filter(OrganizationMembership.organization_id == organization_id)
                             .order_by(OrganizationMembership.created_at)):
        sessions_now = db.query(UserSession).filter(UserSession.user_id == user.id,
                                                    UserSession.organization_id == organization_id,
                                                    UserSession.ended_at.is_(None), UserSession.expires_at > now).count()
        members.append(MemberResponse(user_id=user.id, display_name=user.display_name, email=user.email,
                                      role=membership.role.value, status=membership.status,
                                      active_sessions=sessions_now))
    return CustomerDetail(
        organization_id=organization.id, organization_name=organization.name, organization_slug=organization.slug,
        created_at=organization.created_at, rows=[_row(row) for row in rows], subscriptions=summaries,
        usage=UsageThisPeriod(**overview.usage_this_period(db, organization_id)), members=members,
        open_alerts=overview._open_alerts(db, organization_id))


@router.post("/customers/{organization_id}/login-history", response_model=AdminLoginPage)
def customer_login_history(
    organization_id: uuid.UUID, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin),
) -> AdminLoginPage:
    """Cross-organisation login history, IP addresses included, is an audited view. It is a POST (security
    review L4) so the audit row can only come from an explicit request carrying the BFF's CSRF token, never from
    a cross-site link that a browser follows with the session cookie."""
    _organization(db, organization_id)
    query = (db.query(UserSession, User).join(User, User.id == UserSession.user_id)
             .filter(UserSession.organization_id == organization_id))
    rows = query.order_by(UserSession.created_at.desc(), UserSession.id).offset(offset).limit(limit).all()
    replaced = {}
    ids = [row.id for row, _ in rows]
    if ids:
        for (replacer,) in db.query(UserSession.replaced_by_id).filter(UserSession.replaced_by_id.in_(ids)):
            replaced[replacer] = replaced.get(replacer, 0) + 1
    now = datetime.now(timezone.utc)
    audit.record(db, admin.actor, "view.login_history", reason="Viewed in the NOVA ARI console.",
                 organization_id=organization_id, target_type="organization", target_id=organization_id,
                 current={"offset": offset, "limit": limit})
    db.commit()
    items = [AdminLoginEntry(
        id=row.id, created_at=row.created_at, user_id=user.id, user_display_name=user.display_name,
        user_email=user.email, browser=row.browser, os=row.os, device_type=row.device_type,
        location=", ".join(part for part in (row.city, row.country) if part) or None, country_code=row.country_code,
        ip_address=row.ip_address, result=row.end_reason or ("active" if row.expires_at > now else "expired"),
        ended_at=row.ended_at, is_new_device=row.is_new_device, ended_earlier_sessions=replaced.get(row.id, 0))
        for row, user in rows]
    return AdminLoginPage(items=items, total=query.count(), limit=limit, offset=offset,
                          location_attribution=ATTRIBUTION if get_settings().geoip_database_path else None)


@router.get("/customers/{organization_id}/ledger", response_model=LedgerPage)
def customer_ledger(
    organization_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin),
) -> LedgerPage:
    _organization(db, organization_id)
    query = db.query(CreditLedgerEntry).filter(CreditLedgerEntry.organization_id == organization_id)
    rows = query.order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id).offset(offset).limit(limit).all()
    plan_names = {plan.key: plan.name for plan in db.query(BillingPlan)}
    return LedgerPage(items=[LedgerEntryResponse(
        id=row.id, created_at=row.created_at, period=row.period, kind=row.kind, bucket=row.bucket, amount=row.amount,
        balance_after=row.balance_after, task_id=row.task_id, reason=row.reason, project_name=None, aoi_name=None,
        plan_name=plan_names.get((row.metadata_json or {}).get("plan_key")) if row.kind == "monthly_grant" else None)
        for row in rows], total=query.count(), limit=limit, offset=offset)


@router.post("/customers/{organization_id}/subscriptions", response_model=CustomerCreated, status_code=201)
def add_subscription(organization_id: uuid.UUID, body: AddSubscriptionRequest, db: Session = Depends(get_db),
                     admin: AdminContext = Depends(require_platform_admin)) -> CustomerCreated:
    _organization(db, organization_id)
    with _errors(db):
        subscription = actions.add_subscription(
            db, organization_id, family=body.family, plan_key=body.plan_key, reason=body.reason, actor=admin.actor,
            starts_at=body.starts_at, ends_at=body.ends_at, overrides=_overrides(body.overrides))
        db.commit()
    return CustomerCreated(organization_id=organization_id, subscription_id=subscription.id, owner_user_id=None)


@router.post("/customers/{organization_id}/sessions/end", response_model=EndSessionsResponse)
def end_sessions(organization_id: uuid.UUID, body: EndSessionsRequest, db: Session = Depends(get_db),
                 admin: AdminContext = Depends(require_platform_admin),
                 tracker: SessionTracker = Depends(get_session_tracker)) -> EndSessionsResponse:
    _organization(db, organization_id)
    with _errors(db):
        try:
            ended = actions.end_sessions(db, tracker, organization_id=organization_id, user_id=body.user_id,
                                         reason=body.reason, actor=admin.actor)
        except (actions.ActionError, audit.ReasonRequired):
            raise
        except Exception as exc:
            db.rollback()
            raise PublicAPIError(503, "sessions_unavailable", "Sessions cannot be changed right now.") from exc
        db.commit()
    return EndSessionsResponse(ended=ended)


# --- subscription actions ---------------------------------------------------------------------------

@router.post("/subscriptions/{subscription_id}/status", response_model=CustomerRowResponse)
def change_status(subscription_id: uuid.UUID, body: StatusChangeRequest, db: Session = Depends(get_db),
                  admin: AdminContext = Depends(require_platform_admin)) -> CustomerRowResponse:
    subscription = _subscription(db, subscription_id)
    with _errors(db):
        kwargs = {"ends_at": body.ends_at} if body.change_ends_at else {}
        statuses.change_status(db, subscription.id, body.status, reason=body.reason, actor=admin.actor, **kwargs)
        db.commit()
    return _row(next(row for row in overview.customer_rows(db) if row.subscription_id == subscription_id))


@router.post("/subscriptions/{subscription_id}/plan", response_model=CustomerRowResponse)
def change_plan(subscription_id: uuid.UUID, body: PlanChangeRequest, db: Session = Depends(get_db),
                admin: AdminContext = Depends(require_platform_admin)) -> CustomerRowResponse:
    _subscription(db, subscription_id)
    with _errors(db):
        actions.change_plan(db, subscription_id, plan_key=body.plan_key, overrides=_overrides(body.overrides), reason=body.reason,
                            actor=admin.actor)
        db.commit()
    return _row(next(row for row in overview.customer_rows(db) if row.subscription_id == subscription_id))


@router.post("/subscriptions/{subscription_id}/payments", response_model=PaymentRecorded, status_code=201)
def record_payment(subscription_id: uuid.UUID, body: RecordPaymentRequest, db: Session = Depends(get_db),
                   admin: AdminContext = Depends(require_platform_admin),
                   idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> PaymentRecorded:
    subscription = _subscription(db, subscription_id)
    key = _key(idempotency_key)
    with _errors(db):
        common = dict(amount=body.amount, method=body.method, paid_on=body.paid_on, reference=body.reference,
                      note=body.note, actor=admin.actor, key=key)
        if body.purpose == "plan_period":
            if body.covers_from is None or body.covers_until is None:
                raise payments.PaymentError("payment_period_invalid", "A plan payment needs the period it covers.")
            result = payments.record_plan_payment(db, subscription.id, covers_from=body.covers_from,
                                                  covers_until=body.covers_until, **common)
        else:
            if body.credits is None:
                raise payments.PaymentError("credits_invalid", "A top-up payment needs the number of credits.")
            result = payments.record_top_up_payment(db, subscription.id, credits=body.credits, **common)
        db.commit()
    return PaymentRecorded(payment=_payment(result.payment, subscription.family, set()),
                           ledger_entry_id=result.entry.id if result.entry else None, replayed=result.replayed)


@router.post("/payments/{payment_id}/reverse", response_model=PaymentRecorded, status_code=201)
def reverse_payment(payment_id: uuid.UUID, body: ReasonRequest, db: Session = Depends(get_db),
                    admin: AdminContext = Depends(require_platform_admin),
                    idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> PaymentRecorded:
    key = _key(idempotency_key)
    with _errors(db):
        result = payments.reverse_payment(db, payment_id, reason=body.reason, actor=admin.actor, key=key)
        db.commit()
    family = db.get(OrganizationSubscription, result.payment.subscription_id).family
    return PaymentRecorded(payment=_payment(result.payment, family, set()),
                           ledger_entry_id=result.entry.id if result.entry else None, replayed=result.replayed)


def _credits_changed(db: Session, entry: CreditLedgerEntry) -> CreditsChanged:
    return CreditsChanged(ledger_entry_id=entry.id, remaining=ledger.balances(db, entry.subscription_id).total)


@router.post("/subscriptions/{subscription_id}/credits", response_model=CreditsChanged, status_code=201)
def add_credits(subscription_id: uuid.UUID, body: GrantCreditsRequest, db: Session = Depends(get_db),
                admin: AdminContext = Depends(require_platform_admin),
                idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> CreditsChanged:
    """"Add credits" without a payment (pilot, goodwill, a manual refund after a software error)."""
    _subscription(db, subscription_id)
    key = _key(idempotency_key)
    with _errors(db):
        entry = payments.grant_top_up(db, subscription_id, credits=body.credits, reason=body.reason, actor=admin.actor,
                                      key=key)
        db.commit()
    return _credits_changed(db, entry)


@router.post("/subscriptions/{subscription_id}/adjustments", response_model=CreditsChanged, status_code=201)
def adjust_credits(subscription_id: uuid.UUID, body: AdjustCreditsRequest, db: Session = Depends(get_db),
                   admin: AdminContext = Depends(require_platform_admin),
                   idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> CreditsChanged:
    _subscription(db, subscription_id)
    key = _key(idempotency_key)
    with _errors(db):
        entry = payments.adjust_credits(db, subscription_id, amount=body.amount, bucket=body.bucket,
                                        reason=body.reason, actor=admin.actor, key=key)
        db.commit()
    return _credits_changed(db, entry)


# --- payments, plans, alerts, audit ----------------------------------------------------------------

@router.get("/payments", response_model=AdminPaymentPage)
def list_payments(
    organization_id: uuid.UUID | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin),
) -> AdminPaymentPage:
    query = db.query(Payment)
    if organization_id is not None:
        query = query.filter(Payment.organization_id == organization_id)
    rows = query.order_by(Payment.paid_on.desc(), Payment.created_at.desc(), Payment.id).offset(offset).limit(limit).all()
    reversed_ids = {value for (value,) in db.query(Payment.reverses_payment_id)
                    .filter(Payment.reverses_payment_id.in_([row.id for row in rows]))} if rows else set()
    orgs = {org.id: org.name for org in db.query(Organization).filter(
        Organization.id.in_({row.organization_id for row in rows}))} if rows else {}
    families = {sub.id: sub.family for sub in db.query(OrganizationSubscription).filter(
        OrganizationSubscription.id.in_({row.subscription_id for row in rows}))} if rows else {}
    users = {user.id: user.display_name or user.email for user in db.query(User).filter(
        User.id.in_({row.recorded_by_user_id for row in rows if row.recorded_by_user_id}))} if rows else {}
    items = [AdminPaymentResponse(
        **_payment(row, families.get(row.subscription_id), reversed_ids).model_dump(),
        organization_id=row.organization_id, organization_name=orgs.get(row.organization_id, ""), note=row.note,
        expected_amount=row.expected_amount, recorded_by=users.get(row.recorded_by_user_id)) for row in rows]
    return AdminPaymentPage(items=items, total=query.count(), limit=limit, offset=offset)


def _plan(item: dict) -> AdminPlan:
    plan, price = item["plan"], item["price"]
    return AdminPlan(
        key=plan.key, family=plan.family, name=plan.name, is_custom=plan.is_custom, is_internal=plan.is_internal,
        unlimited_credits=plan.unlimited_credits,
        limits=PlanLimits(seat_limit=plan.seat_limit, monthly_credits=plan.monthly_credits,
                          storage_bytes=plan.storage_bytes, session_limit=plan.session_limit),
        refund_on_data_failure=plan.refund_on_data_failure, currency=price.currency if price else "TZS",
        monthly_price=price.monthly_price if price else None,
        top_up_credit_price=price.top_up_credit_price if price else None,
        price_version=price.version if price else None, subscriptions=item["subscriptions"])


@router.get("/plans", response_model=list[AdminPlan])
def list_plans(db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin)) -> list[AdminPlan]:
    return [_plan(item) for item in overview.plan_catalogue(db)]


@router.post("/plans/{plan_key}/prices", response_model=AdminPlan, status_code=201)
def change_price(plan_key: str, body: PriceChangeRequest, db: Session = Depends(get_db),
                 admin: AdminContext = Depends(require_platform_admin)) -> AdminPlan:
    with _errors(db):
        actions.new_price_version(db, plan_key, monthly_price=body.monthly_price,
                                  top_up_credit_price=body.top_up_credit_price, reason=body.reason, actor=admin.actor)
        db.commit()
    return _plan(next(item for item in overview.plan_catalogue(db) if item["plan"].key == plan_key))


@router.patch("/plans/{plan_key}/limits", response_model=AdminPlan)
def change_limits(plan_key: str, body: LimitChangeRequest, db: Session = Depends(get_db),
                  admin: AdminContext = Depends(require_platform_admin)) -> AdminPlan:
    with _errors(db):
        actions.update_plan_limits(db, plan_key, changes={name: getattr(body, name) for name in body.fields},
                                   reason=body.reason, actor=admin.actor)
        db.commit()
    return _plan(next(item for item in overview.plan_catalogue(db) if item["plan"].key == plan_key))


@router.get("/security-alerts", response_model=SecurityAlertPage)
def list_alerts(
    state: str = Query("open", pattern="^(open|all)$"), organization_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin),
) -> SecurityAlertPage:
    query = (db.query(SecurityAlert, Organization, User)
             .join(Organization, Organization.id == SecurityAlert.organization_id)
             .join(User, User.id == SecurityAlert.user_id))
    if state == "open":
        query = query.filter(SecurityAlert.acknowledged_at.is_(None))
    if organization_id is not None:
        query = query.filter(SecurityAlert.organization_id == organization_id)
    rows = query.order_by(SecurityAlert.created_at.desc(), SecurityAlert.id).offset(offset).limit(limit).all()
    reviewers = {user.id: user.display_name or user.email for user in db.query(User).filter(
        User.id.in_({alert.acknowledged_by_user_id for alert, _, _ in rows if alert.acknowledged_by_user_id}))} \
        if rows else {}
    return SecurityAlertPage(items=[SecurityAlertResponse(
        id=alert.id, created_at=alert.created_at, kind=alert.kind, organization_id=organization.id,
        organization_name=organization.name, user_id=user.id, user_display_name=user.display_name,
        user_email=user.email, detail=alert.detail, acknowledged_at=alert.acknowledged_at,
        acknowledged_by=reviewers.get(alert.acknowledged_by_user_id), acknowledge_reason=alert.acknowledge_reason)
        for alert, organization, user in rows], total=query.count(), limit=limit, offset=offset)


@router.post("/security-alerts/{alert_id}/acknowledge", response_model=ReasonRequest)
def acknowledge_alert(alert_id: uuid.UUID, body: ReasonRequest, db: Session = Depends(get_db),
                      admin: AdminContext = Depends(require_platform_admin)) -> ReasonRequest:
    with _errors(db):
        actions.acknowledge_alert(db, alert_id, reason=body.reason, actor=admin.actor)
        db.commit()
    return body


@router.get("/audit", response_model=AuditPage)
def list_audit(
    organization_id: uuid.UUID | None = None, action: str | None = Query(None, max_length=80),
    actor_user_id: uuid.UUID | None = None, q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin),
) -> AuditPage:
    query = db.query(PlatformAudit)
    if organization_id is not None:
        query = query.filter(PlatformAudit.organization_id == organization_id)
    if action:
        query = query.filter(PlatformAudit.action.startswith(action))
    if actor_user_id is not None:
        query = query.filter(PlatformAudit.actor_user_id == actor_user_id)
    if q:
        query = query.filter(or_(PlatformAudit.reason.ilike(f"%{q}%"), PlatformAudit.actor_label.ilike(f"%{q}%")))
    rows = query.order_by(PlatformAudit.created_at.desc(), PlatformAudit.id).offset(offset).limit(limit).all()
    orgs = {org.id: org.name for org in db.query(Organization).filter(
        Organization.id.in_({row.organization_id for row in rows if row.organization_id}))} if rows else {}
    return AuditPage(items=[AuditEntry(
        id=row.id, created_at=row.created_at, actor_user_id=row.actor_user_id, actor=row.actor_label,
        action=row.action, organization_id=row.organization_id, organization_name=orgs.get(row.organization_id),
        target_type=row.target_type, target_id=row.target_id, previous=row.previous, current=row.current,
        reason=row.reason, request_id=row.request_id) for row in rows], total=query.count(), limit=limit,
        offset=offset)


# --- customer requests (top-up, upgrade) ------------------------------------------------------------

@router.get("/requests", response_model=AdminRequestPage)
def list_customer_requests(
    state: str = Query("open", pattern="^(open|all)$"), limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0), db: Session = Depends(get_db), admin: AdminContext = Depends(require_platform_admin),
) -> AdminRequestPage:
    query = db.query(SubscriptionRequest)
    if state == "open":
        query = query.filter(SubscriptionRequest.status == "open")
    rows = query.order_by(SubscriptionRequest.created_at.desc(), SubscriptionRequest.id).offset(offset).limit(limit).all()
    orgs = {org.id: org.name for org in db.query(Organization).filter(
        Organization.id.in_({row.organization_id for row in rows}))} if rows else {}
    subs = {sub.id: sub for sub in db.query(OrganizationSubscription).filter(
        OrganizationSubscription.id.in_({row.subscription_id for row in rows}))} if rows else {}
    user_ids = {row.requested_by_user_id for row in rows} | {row.closed_by_user_id for row in rows if row.closed_by_user_id}
    users = {user.id: user.display_name or user.email for user in db.query(User).filter(User.id.in_(user_ids))} if rows else {}
    plans = {plan.key: plan.name for plan in db.query(BillingPlan)}
    items = []
    for row in rows:
        subscription = subs.get(row.subscription_id)
        items.append(AdminRequest(
            id=row.id, created_at=row.created_at, organization_id=row.organization_id,
            organization_name=orgs.get(row.organization_id, ""), subscription_id=row.subscription_id,
            family=subscription.family if subscription else None,
            current_plan=plans.get(subscription.plan_key) if subscription else None, kind=row.kind,
            plan_key=row.plan_key, plan_name=plans.get(row.plan_key), credits=row.credits, note=row.note,
            requested_by=users.get(row.requested_by_user_id), status=row.status, closed_at=row.closed_at,
            closed_by=users.get(row.closed_by_user_id), close_reason=row.close_reason))
    return AdminRequestPage(items=items, total=query.count(), limit=limit, offset=offset)


@router.post("/requests/{request_id}/close", response_model=CloseRequest)
def close_customer_request(request_id: uuid.UUID, body: CloseRequest, db: Session = Depends(get_db),
                           admin: AdminContext = Depends(require_platform_admin)) -> CloseRequest:
    """Close after acting on it (record the payment or change the plan first), or decline it."""
    with _errors(db):
        billing_requests.close(db, request_id, outcome=body.outcome, reason=body.reason, actor=admin.actor)
        db.commit()
    return body
