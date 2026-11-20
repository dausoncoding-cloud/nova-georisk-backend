"""Append-only credit ledger: balances, idempotent entries, monthly grants, expiry, usage thresholds.

Callers must hold the subscription row lock (`lock_subscription`) for every write, so balance checks
and the idempotency check cannot race. Nothing here commits; the caller owns the transaction.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.billing import CreditLedgerEntry, CreditUsageNotice
from app.models.platform import BillingPlan, OrganizationSubscription, SubscriptionStatus

WARNING_LEVELS = (75, 90)
MAX_CATCH_UP_MONTHS = 12


class InsufficientCredits(Exception):
    pass


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class Balances:
    monthly: int
    top_up: int

    @property
    def total(self) -> int:
        return self.monthly + self.top_up

    def of(self, bucket: str) -> int:
        return self.monthly if bucket == "monthly" else self.top_up


@dataclass(frozen=True)
class Usage:
    period: str
    granted: int
    top_ups: int
    used: int
    remaining: int
    level: int | None  # None, 75, 90 or 100

    @property
    def available(self) -> int:
        return self.used + self.remaining

    @property
    def used_percent(self) -> float:
        return 100.0 if self.available <= 0 else round(100.0 * self.used / self.available, 1)


# --- periods -------------------------------------------------------------------------------------

def _zone() -> ZoneInfo:
    return ZoneInfo(get_settings().billing_timezone)


def period_of(at: datetime | None = None) -> str:
    at = at or datetime.now(timezone.utc)
    return at.astimezone(_zone()).strftime("%Y-%m")


def next_period(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    return f"{year + month // 12}-{month % 12 + 1:02d}"


def period_start(period: str) -> datetime:
    year, month = (int(part) for part in period.split("-"))
    return datetime(year, month, 1, tzinfo=_zone())


# --- subscription helpers -------------------------------------------------------------------------

def lock_subscription(db: Session, subscription_id: uuid.UUID) -> OrganizationSubscription:
    subscription = (
        db.query(OrganizationSubscription)
        .filter(OrganizationSubscription.id == subscription_id)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if subscription is None:
        raise LedgerError("Subscription not found.")
    return subscription


def _plan(db: Session, subscription: OrganizationSubscription) -> BillingPlan | None:
    return db.get(BillingPlan, subscription.plan_key) if subscription.plan_key else None


def effective_monthly_credits(db: Session, subscription: OrganizationSubscription) -> int:
    if subscription.monthly_credits_override is not None:
        return subscription.monthly_credits_override
    plan = _plan(db, subscription)
    return (plan.monthly_credits if plan and plan.monthly_credits is not None else 0)


def refund_on_data_failure(db: Session, subscription: OrganizationSubscription) -> bool:
    if subscription.refund_on_data_failure_override is not None:
        return subscription.refund_on_data_failure_override
    plan = _plan(db, subscription)
    return bool(plan and plan.refund_on_data_failure)


def is_current(subscription: OrganizationSubscription, at: datetime | None = None) -> bool:
    """Active (or an unexpired trial) and inside its dates: may receive grants and submit analyses."""
    at = at or datetime.now(timezone.utc)
    if subscription.status not in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL}:
        return False
    if subscription.starts_at is not None and subscription.starts_at > at:
        return False
    if subscription.ends_at is not None and subscription.ends_at <= at:
        return False
    if subscription.status == SubscriptionStatus.TRIAL:
        return subscription.trial_ends_at is not None and subscription.trial_ends_at > at
    return True


# --- balances and entries -------------------------------------------------------------------------

def balances(db: Session, subscription_id: uuid.UUID) -> Balances:
    monthly, top_up = (
        db.query(
            func.coalesce(func.sum(case((CreditLedgerEntry.bucket == "monthly", CreditLedgerEntry.amount), else_=0)), 0),
            func.coalesce(func.sum(case((CreditLedgerEntry.bucket == "top_up", CreditLedgerEntry.amount), else_=0)), 0),
        )
        .filter(CreditLedgerEntry.subscription_id == subscription_id)
        .one()
    )
    return Balances(monthly=int(monthly), top_up=int(top_up))


def entry_by_key(db: Session, key: str) -> CreditLedgerEntry | None:
    return db.query(CreditLedgerEntry).filter(CreditLedgerEntry.idempotency_key == key).one_or_none()


def append_entry(
    db: Session,
    subscription: OrganizationSubscription,
    *,
    kind: str,
    bucket: str,
    amount: int,
    key: str,
    period: str | None = None,
    task_id: uuid.UUID | None = None,
    payment_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    reason: str | None = None,
    metadata: dict | None = None,
) -> CreditLedgerEntry:
    """Write one entry, or return the existing entry with the same idempotency key. Lock must be held."""
    existing = entry_by_key(db, key)
    if existing is not None:
        if existing.subscription_id != subscription.id or existing.kind != kind:
            raise LedgerError("Idempotency key is already used by a different ledger entry.")
        return existing
    if amount == 0:
        raise LedgerError("Ledger amounts must be non-zero.")
    if kind == "adjustment" and not (reason and reason.strip()):
        raise LedgerError("An adjustment needs a reason.")
    current = balances(db, subscription.id)
    bucket_after = current.of(bucket) + amount
    if bucket_after < 0:
        raise InsufficientCredits("Not enough credits.")
    entry = CreditLedgerEntry(
        subscription_id=subscription.id,
        organization_id=subscription.organization_id,
        kind=kind,
        bucket=bucket,
        amount=amount,
        balance_after=current.total + amount,
        bucket_balance_after=bucket_after,
        period=period or period_of(),
        task_id=task_id,
        payment_id=payment_id,
        actor_user_id=actor_user_id,
        reason=reason.strip() if reason else None,
        idempotency_key=key,
        metadata_json=metadata,
    )
    db.add(entry)
    db.flush()
    return entry


# --- monthly grant and expiry ---------------------------------------------------------------------

def grant_key(subscription_id: uuid.UUID, period: str) -> str:
    return f"grant:{subscription_id}:{period}"


def _last_grant_period(db: Session, subscription_id: uuid.UUID) -> str | None:
    return (
        db.query(func.max(CreditLedgerEntry.period))
        .filter(CreditLedgerEntry.subscription_id == subscription_id, CreditLedgerEntry.kind == "monthly_grant")
        .scalar()
    )


def _expire_bucket(db: Session, subscription: OrganizationSubscription, bucket: str, period: str) -> None:
    held = balances(db, subscription.id).of(bucket)
    if held > 0:
        append_entry(db, subscription, kind="expiry", bucket=bucket, amount=-held, period=period,
                     key=f"expire:{subscription.id}:{period}:{bucket}",
                     reason="Unused credits expired at the end of the billing month.")


def ensure_period(db: Session, subscription: OrganizationSubscription, at: datetime | None = None) -> None:
    """Bring the subscription up to the current billing month: expire last month's credits (per policy),
    then write this month's grant once. Idempotent; safe to call on every read or write. Lock must be held."""
    at = at or datetime.now(timezone.utc)
    current = period_of(at)
    if entry_by_key(db, grant_key(subscription.id, current)) is not None:
        return
    settings = get_settings()
    last = _last_grant_period(db, subscription.id)
    if last is not None and last < current:
        if not settings.billing_monthly_credits_roll_over:
            _expire_bucket(db, subscription, "monthly", current)
        if settings.billing_top_up_credits_expire:
            _expire_bucket(db, subscription, "top_up", current)
    if not is_current(subscription, at):
        return
    credits = effective_monthly_credits(db, subscription)
    if credits <= 0:
        return
    periods = [current]
    if settings.billing_monthly_credits_roll_over and last is not None and last < current:
        periods, cursor = [], next_period(last)
        while cursor <= current and len(periods) < MAX_CATCH_UP_MONTHS:
            periods.append(cursor)
            cursor = next_period(cursor)
        if periods[-1] != current:
            periods.append(current)
    for period in periods:
        append_entry(db, subscription, kind="monthly_grant", bucket="monthly", amount=credits, period=period,
                     key=grant_key(subscription.id, period), metadata={"plan_key": subscription.plan_key})


# --- charges and refunds --------------------------------------------------------------------------

def charge_task(
    db: Session, subscription: OrganizationSubscription, task_id: uuid.UUID, actor_user_id: uuid.UUID | None,
    engine_key: str,
) -> CreditLedgerEntry:
    """1 analysis = 1 credit; monthly credits are spent before top-ups. Lock must be held."""
    existing = entry_by_key(db, f"charge:{task_id}")
    if existing is not None:
        return existing
    held = balances(db, subscription.id)
    if held.total <= 0:
        raise InsufficientCredits("No credits left.")
    bucket = "monthly" if held.monthly > 0 else "top_up"
    entry = append_entry(db, subscription, kind="charge", bucket=bucket, amount=-1, key=f"charge:{task_id}",
                         task_id=task_id, actor_user_id=actor_user_id, metadata={"engine_key": engine_key})
    record_threshold_notices(db, subscription)
    return entry


def refund_task(
    db: Session, subscription: OrganizationSubscription, task_id: uuid.UUID, *, reason: str, cause: str,
) -> CreditLedgerEntry | None:
    """At most one refund per task, back to the bucket the charge came from. Lock must be held."""
    charge = entry_by_key(db, f"charge:{task_id}")
    if charge is None:
        return None
    ensure_period(db, subscription)
    return append_entry(db, subscription, kind="refund", bucket=charge.bucket, amount=-charge.amount,
                        key=f"refund:{task_id}", task_id=task_id, reason=reason, metadata={"cause": cause})


# --- usage and thresholds -------------------------------------------------------------------------

def usage(db: Session, subscription: OrganizationSubscription, at: datetime | None = None) -> Usage:
    period = period_of(at)
    rows = dict(
        db.query(CreditLedgerEntry.kind, func.coalesce(func.sum(CreditLedgerEntry.amount), 0))
        .filter(CreditLedgerEntry.subscription_id == subscription.id, CreditLedgerEntry.period == period)
        .group_by(CreditLedgerEntry.kind)
        .all()
    )
    used = max(0, -int(rows.get("charge", 0)) - int(rows.get("refund", 0)))
    remaining = balances(db, subscription.id).total
    level = _level(used, remaining)
    return Usage(period=period, granted=int(rows.get("monthly_grant", 0)), top_ups=int(rows.get("top_up", 0)),
                 used=used, remaining=remaining, level=level)


def _level(used: int, remaining: int) -> int | None:
    if remaining <= 0:
        return 100
    percent = 100.0 * used / (used + remaining)
    for threshold in reversed(WARNING_LEVELS):
        if percent >= threshold:
            return threshold
    return None


def record_threshold_notices(db: Session, subscription: OrganizationSubscription) -> list[int]:
    """Record each level the subscription has reached this month, once (for the email channel)."""
    current = usage(db, subscription)
    if current.level is None:
        return []
    reached = [level for level in (*WARNING_LEVELS, 100) if level <= current.level]
    existing = {
        row.level for row in db.query(CreditUsageNotice).filter(
            CreditUsageNotice.subscription_id == subscription.id, CreditUsageNotice.period == current.period)
    }
    new = [level for level in reached if level not in existing]
    for level in new:
        db.add(CreditUsageNotice(subscription_id=subscription.id, organization_id=subscription.organization_id,
                                 period=current.period, level=level))
    if new:
        db.flush()
    return new
