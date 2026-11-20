"""Read models for the NOVA ARI console (board 14): KPI tiles, the customers table with flags, usage this
period. Computed per request from the ledger, payments, sessions, alerts and usage tables; sized for
hundreds of customers (filtering and paging happen after the rows are built)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.billing import CreditLedgerEntry, Payment
from app.models.identity import Organization, OrganizationMembership, User
from app.models.platform import BillingPlan, OrganizationSubscription, SubscriptionStatus
from app.models.platform_admin import OrganizationUsageDaily, SecurityAlert, SubscriptionRequest
from app.models.project import Project
from app.models.sessions import UserSession
from app.models.task import Task
from app.services.billing import catalogue, ledger, limits

FLAGS = ("payment_overdue", "expiring_soon", "new_device", "credits_low", "storage_high", "suspended", "request_open")


def _today() -> date:
    return datetime.now(timezone.utc).astimezone(ledger._zone()).date()


# --- payments ---------------------------------------------------------------------------------------

def paid_through(db: Session, subscription_id: uuid.UUID) -> date | None:
    """The last day covered by a plan payment that has not been reversed."""
    reversed_ids = db.query(Payment.reverses_payment_id).filter(Payment.reverses_payment_id.isnot(None))
    return (db.query(func.max(Payment.covers_until))
            .filter(Payment.subscription_id == subscription_id, Payment.purpose == "plan_period",
                    Payment.id.notin_(reversed_ids))
            .scalar())


def payment_overdue(db: Session, subscription: OrganizationSubscription, plan: BillingPlan | None,
                    today: date | None = None) -> bool:
    """An Active, sold subscription whose paid period ended more than the grace days ago (or which started
    that long ago with no plan payment). Internal plans and inactive subscriptions are never overdue.
    With BILLING_OVERDUE_GRACE_FROM (the go-live date), nothing before that date is judged: the unpaid
    period counts from the go-live date at the earliest."""
    if subscription.status != SubscriptionStatus.ACTIVE or plan is None or plan.is_internal:
        return False
    today = today or _today()
    settings = get_settings()
    grace = timedelta(days=settings.billing_payment_overdue_grace_days)
    base = paid_through(db, subscription.id)  # last paid day, or the start date when nothing is paid yet
    if base is None:
        start = subscription.starts_at or subscription.created_at
        if start is None:
            return False
        base = start.astimezone(ledger._zone()).date()
    if settings.billing_overdue_grace_from is not None and base < settings.billing_overdue_grace_from:
        base = settings.billing_overdue_grace_from
    return today > base + grace


def expiring_soon(subscription: OrganizationSubscription, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    window = timedelta(days=get_settings().billing_expiring_soon_days)
    return (subscription.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL}
            and subscription.ends_at is not None and now < subscription.ends_at <= now + window)


# --- rows -------------------------------------------------------------------------------------------

@dataclass
class CustomerRow:
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    subscription_id: uuid.UUID | None
    family: str | None
    systems: list[str]
    plan_key: str | None
    plan_name: str | None
    is_internal: bool
    status: str | None
    users_used: int
    users_limit: int | None
    active_sessions: int
    session_limit: int | None
    credits_used: int
    credits_available: int
    credits_unlimited: bool
    storage_used: int
    storage_limit: int | None
    ends_at: datetime | None
    renews_on: datetime | None
    flags: list[str] = field(default_factory=list)


def _family_label(family: str | None) -> list[str]:
    if family is None:
        return []
    return {"frris_wrris": ["FRRIS", "WRRIS"], "megis": ["MEGIS"]}.get(family, [family])


def _active_sessions(db: Session, organization_id: uuid.UUID, now: datetime) -> int:
    return db.query(UserSession).filter(UserSession.organization_id == organization_id,
                                        UserSession.ended_at.is_(None), UserSession.expires_at > now).count()


def _open_alerts(db: Session, organization_id: uuid.UUID) -> int:
    return db.query(SecurityAlert).filter(SecurityAlert.organization_id == organization_id,
                                          SecurityAlert.acknowledged_at.is_(None)).count()


def customer_rows(db: Session) -> list[CustomerRow]:
    """One row per subscription, plus one per organisation without any subscription. Brings each
    subscription to the current billing month first (idempotent), so credits are current."""
    now = datetime.now(timezone.utc)
    rows: list[CustomerRow] = []
    plans = {plan.key: plan for plan in db.query(BillingPlan)}
    open_requests = {sub_id for (sub_id,) in db.query(SubscriptionRequest.subscription_id)
                     .filter(SubscriptionRequest.status == "open")}
    for organization in db.query(Organization).order_by(Organization.name):
        subscriptions = limits.subscriptions(db, organization.id)
        seats = limits.seats(db, organization.id)
        storage = limits.storage(db, organization.id)
        sessions_now = _active_sessions(db, organization.id, now)
        session_limit = max([v for v in (ledger.effective_limits(db, s)["session_limit"] for s in subscriptions)
                             if v is not None], default=None)
        alerts = _open_alerts(db, organization.id)
        if not subscriptions:
            rows.append(CustomerRow(
                organization_id=organization.id, organization_name=organization.name,
                organization_slug=organization.slug, subscription_id=None, family=None, systems=[],
                plan_key=None, plan_name=None, is_internal=False, status=None, users_used=seats.used,
                users_limit=None, active_sessions=sessions_now, session_limit=None, credits_used=0,
                credits_available=0, credits_unlimited=False, storage_used=storage.used, storage_limit=None,
                ends_at=None, renews_on=None, flags=["new_device"] if alerts else []))
            continue
        for subscription in subscriptions:
            locked = ledger.lock_subscription(db, subscription.id)
            ledger.ensure_period(db, locked)
            db.commit()
            subscription = db.get(OrganizationSubscription, subscription.id)
            plan = plans.get(subscription.plan_key)
            unlimited = bool(plan and plan.unlimited_credits)
            usage = ledger.usage(db, subscription)
            flags = []
            if payment_overdue(db, subscription, plan):
                flags.append("payment_overdue")
            if expiring_soon(subscription, now):
                flags.append("expiring_soon")
            if alerts:
                flags.append("new_device")
            if not unlimited and usage.level is not None and usage.level >= 90:
                flags.append("credits_low")
            if storage.level is not None and storage.level >= 90:
                flags.append("storage_high")
            if subscription.status == SubscriptionStatus.SUSPENDED:
                flags.append("suspended")
            if subscription.id in open_requests:
                flags.append("request_open")
            rows.append(CustomerRow(
                organization_id=organization.id, organization_name=organization.name,
                organization_slug=organization.slug, subscription_id=subscription.id, family=subscription.family,
                systems=_family_label(subscription.family), plan_key=subscription.plan_key,
                plan_name=plan.name if plan else None, is_internal=bool(plan and plan.is_internal),
                status=subscription.status.value, users_used=seats.used, users_limit=seats.limit,
                active_sessions=sessions_now, session_limit=session_limit, credits_used=usage.used,
                credits_available=usage.available, credits_unlimited=unlimited, storage_used=storage.used,
                storage_limit=storage.limit, ends_at=subscription.ends_at, renews_on=ledger.renews_on(subscription),
                flags=flags))
    return rows


def filter_rows(db: Session, rows: list[CustomerRow], *, q: str | None, status: str | None, family: str | None,
                flag: str | None) -> list[CustomerRow]:
    if q:
        needle = q.strip().lower()
        by_email = {org_id for (org_id,) in db.query(OrganizationMembership.organization_id)
                    .join(User, User.id == OrganizationMembership.user_id)
                    .filter(User.email.ilike(f"%{needle}%"))}
        rows = [row for row in rows if needle in row.organization_name.lower() or needle in row.organization_slug.lower()
                or row.organization_id in by_email]
    if status:
        rows = [row for row in rows if (row.status or "none") == status]
    if family:
        rows = [row for row in rows if row.family == family]
    if flag:
        rows = [row for row in rows if flag in row.flags]
    return rows


# --- tiles ------------------------------------------------------------------------------------------

def tiles(db: Session, rows: list[CustomerRow]) -> dict:
    period = ledger.period_of()
    internal = [key for (key,) in db.query(BillingPlan.key).filter(BillingPlan.is_internal.is_(True))]
    sold = db.query(OrganizationSubscription.id).filter(
        OrganizationSubscription.family.isnot(None),
        or_(OrganizationSubscription.plan_key.is_(None), OrganizationSubscription.plan_key.notin_(internal)))
    used = db.query(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).filter(
        CreditLedgerEntry.period == period, CreditLedgerEntry.kind.in_(("charge", "refund")),
        CreditLedgerEntry.subscription_id.in_(sold)).scalar()
    return {
        "active_subscriptions": sum(1 for row in rows if row.status == "active"),
        "expiring_soon": sum(1 for row in rows if "expiring_soon" in row.flags),
        "expiring_soon_days": get_settings().billing_expiring_soon_days,
        "credits_used_this_month": max(0, -int(used or 0)),
        "open_security_alerts": db.query(SecurityAlert).filter(SecurityAlert.acknowledged_at.is_(None)).count(),
        "payments_overdue": sum(1 for row in rows if "payment_overdue" in row.flags),
        "customers": len({row.organization_id for row in rows}),
        "period": period,
    }


# --- usage this period ------------------------------------------------------------------------------

_RESULT_BYTES_IN_PERIOD = text("""
    SELECT coalesce(sum((entry.value ->> 'file_size_bytes')::bigint), 0)
    FROM results r
    JOIN projects p ON p.id = r.project_id
    CROSS JOIN LATERAL jsonb_each(
        CASE WHEN jsonb_typeof(r.output_files) = 'object' THEN r.output_files ELSE '{}'::jsonb END) AS entry
    WHERE p.organization_id = :organization_id AND r.created_at >= :start AND r.created_at < :end
      AND jsonb_typeof(entry.value) = 'object'
      AND (entry.value ->> 'file_size_bytes') ~ '^[0-9]{1,18}$'
""")


def usage_this_period(db: Session, organization_id: uuid.UUID, period: str | None = None) -> dict:
    """Analyses run, data processed (bytes of results produced), downloads, API requests and devices,
    for one billing month."""
    period = period or ledger.period_of()
    start = ledger.period_start(period)
    end = ledger.period_start(ledger.next_period(period))
    analyses = (db.query(Task).join(Project, Project.id == Task.project_id)
                .filter(Project.organization_id == organization_id, Task.created_at >= start, Task.created_at < end)
                .count())
    processed = db.execute(_RESULT_BYTES_IN_PERIOD, {"organization_id": organization_id, "start": start,
                                                     "end": end}).scalar()
    counted = (db.query(func.coalesce(func.sum(OrganizationUsageDaily.api_requests), 0),
                        func.coalesce(func.sum(OrganizationUsageDaily.downloads), 0),
                        func.coalesce(func.sum(OrganizationUsageDaily.download_bytes), 0))
               .filter(OrganizationUsageDaily.organization_id == organization_id,
                       OrganizationUsageDaily.day >= start.date(), OrganizationUsageDaily.day < end.date())
               .one())
    now = datetime.now(timezone.utc)
    devices = (db.query(UserSession.user_id, UserSession.browser, UserSession.os)
               .filter(UserSession.organization_id == organization_id, UserSession.ended_at.is_(None),
                       UserSession.expires_at > now).distinct().count())
    return {"period": period, "analyses_run": analyses, "data_processed_bytes": int(processed or 0),
            "api_requests": int(counted[0]), "downloads": int(counted[1]), "download_bytes": int(counted[2]),
            "registered_devices": devices}


def plan_catalogue(db: Session) -> list[dict]:
    out = []
    for plan in db.query(BillingPlan).filter(BillingPlan.family.isnot(None)).order_by(BillingPlan.family,
                                                                                       BillingPlan.sort_order):
        price = catalogue.current_price(db, plan.key)
        out.append({"plan": plan, "price": price,
                    "subscriptions": db.query(OrganizationSubscription).filter(
                        OrganizationSubscription.plan_key == plan.key).count()})
    return out
