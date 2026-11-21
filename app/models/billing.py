"""Subscription billing records: versioned prices, the append-only credit ledger, submission idempotency,
manual payments and the platform audit trail.

See docs/PLATFORM_SUBSCRIPTIONS_PLAN.md sections 2-5 and 8. Ledger, price, payment and platform-audit rows
are never updated or deleted (database triggers enforce it); a correction is a new row.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (DDL, BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, event)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

LEDGER_KINDS = ("monthly_grant", "top_up", "charge", "refund", "adjustment", "expiry")
LEDGER_BUCKETS = ("monthly", "top_up")
PAYMENT_METHODS = ("bank_transfer", "mobile_money", "cash", "other")
PAYMENT_PURPOSES = ("plan_period", "top_up", "reversal")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BillingPlanPrice(UUIDPrimaryKeyMixin, Base):
    """One price version of a plan (TZS, whole shillings). The current price is the newest effective version."""

    __tablename__ = "billing_plan_prices"
    __table_args__ = (
        UniqueConstraint("plan_key", "version", name="uq_plan_price_version"),
        CheckConstraint("version > 0", name="ck_plan_price_version_positive"),
        CheckConstraint("monthly_price IS NULL OR monthly_price >= 0", name="ck_plan_price_non_negative"),
        CheckConstraint("top_up_credit_price IS NULL OR top_up_credit_price > 0", name="ck_plan_topup_price_positive"),
    )

    plan_key: Mapped[str] = mapped_column(String(64), ForeignKey("billing_plans.key"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TZS")
    # NULL monthly price = custom (contract) plan.
    monthly_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # NULL = top-ups unavailable for this plan until the price is decided (for example MEGIS, Q2).
    top_up_credit_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class CreditLedgerEntry(UUIDPrimaryKeyMixin, Base):
    """Append-only credit movement. Balance = sum(amount); `bucket` separates expiring monthly credits."""

    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('monthly_grant','top_up','charge','refund','adjustment','expiry')",
                        name="ck_ledger_kind"),
        CheckConstraint("bucket IN ('monthly','top_up')", name="ck_ledger_bucket"),
        CheckConstraint("amount <> 0", name="ck_ledger_amount_nonzero"),
        CheckConstraint("balance_after >= 0", name="ck_ledger_balance_non_negative"),
        CheckConstraint("bucket_balance_after >= 0", name="ck_ledger_bucket_balance_non_negative"),
        CheckConstraint(
            "(kind IN ('monthly_grant','top_up','refund') AND amount > 0) OR "
            "(kind IN ('charge','expiry') AND amount < 0) OR kind = 'adjustment'",
            name="ck_ledger_amount_sign",
        ),
        CheckConstraint("kind <> 'adjustment' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
                        name="ck_ledger_adjustment_reason"),
        CheckConstraint("kind NOT IN ('charge','refund') OR task_id IS NOT NULL", name="ck_ledger_task_link"),
        CheckConstraint("period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_ledger_period_format"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_subscriptions.id"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    bucket: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    # Billing month (YYYY-MM in the billing time zone) the entry belongs to.
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    # Plain UUIDs, not foreign keys: the ledger must outlive deleted projects/tasks and never be cascaded.
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class SubmissionIdempotencyKey(UUIDPrimaryKeyMixin, Base):
    """Maps a browser `Idempotency-Key` to the task it created, so a retried request never makes a second task."""

    __tablename__ = "submission_idempotency_keys"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", "key", name="uq_submission_idempotency"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class CreditUsageNotice(UUIDPrimaryKeyMixin, Base):
    """First time a subscription crossed 75/90/100% in a billing month (drives once-per-month warnings)."""

    __tablename__ = "credit_usage_notices"
    __table_args__ = (
        UniqueConstraint("subscription_id", "period", "level", name="uq_credit_usage_notice"),
        CheckConstraint("level IN (75, 90, 100)", name="ck_credit_usage_notice_level"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_subscriptions.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    # Set when an email/notification channel has delivered it (real-time alerts plan); NULL until then.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Payment(UUIDPrimaryKeyMixin, Base):
    """A payment NOVA ARI received outside the app (no gateway in v1). Never edited: a mistake is reversed
    by a new negative `reversal` row that names the original (at most one reversal per payment)."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("method IN ('bank_transfer','mobile_money','cash','other')", name="ck_payment_method"),
        CheckConstraint("purpose IN ('plan_period','top_up','reversal')", name="ck_payment_purpose"),
        CheckConstraint("(purpose = 'reversal') = (amount < 0)", name="ck_payment_sign"),
        CheckConstraint("amount <> 0", name="ck_payment_amount_nonzero"),
        CheckConstraint("purpose <> 'top_up' OR (credits IS NOT NULL AND credits > 0)", name="ck_payment_topup_credits"),
        CheckConstraint("purpose <> 'plan_period' OR (covers_from IS NOT NULL AND covers_until IS NOT NULL "
                        "AND covers_until >= covers_from)", name="ck_payment_period"),
        CheckConstraint("(purpose = 'reversal') = (reverses_payment_id IS NOT NULL)", name="ck_payment_reversal_link"),
        CheckConstraint("purpose <> 'reversal' OR (note IS NOT NULL AND length(trim(note)) > 0)",
                        name="ck_payment_reversal_reason"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"),
                                                       nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization_subscriptions.id"),
                                                       nullable=False, index=True)
    # Whole TZS, signed: negative only for a reversal.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TZS")
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    covers_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    covers_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # List price at recording time (credits x top-up price), for display; None when no price is set (MEGIS, Q2).
    expected_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reverses_payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"),
                                                                  nullable=True, unique=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"),
                                                                  nullable=True)
    # The admin request's key, so a double-clicked "Record payment" records one payment.
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # SHA-256 of the request the key was first used with; the same key with a different request is a 409.
    request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class PlatformAudit(UUIDPrimaryKeyMixin, Base):
    """Every NOVA ARI action on a customer account (plan section 8): who, what, which organisation,
    before and after, and a required reason. Operator commands record `actor_label` and no user."""

    __tablename__ = "platform_audit"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="ck_platform_audit_reason"),
        CheckConstraint("actor_user_id IS NOT NULL OR actor_label IS NOT NULL", name="ck_platform_audit_actor"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"),
                                                              nullable=True, index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    current: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)


# Immutability (mirrors access_audit). Shared by the migration and by create_all in tests.
IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION nova_immutable_billing_record() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' rows are append-only'; END; $$ LANGUAGE plpgsql"""
IMMUTABLE_TABLES = ("credit_ledger_entries", "billing_plan_prices", "payments", "platform_audit")


def immutable_trigger_ddl(table: str) -> list[str]:
    return [
        f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION nova_immutable_billing_record()",
        f"CREATE TRIGGER immutable_{table}_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION nova_immutable_billing_record()",
    ]


for _model in (CreditLedgerEntry, BillingPlanPrice, Payment, PlatformAudit):
    event.listen(_model.__table__, "after_create", DDL(IMMUTABLE_FUNCTION).execute_if(dialect="postgresql"))
    for _statement in immutable_trigger_ddl(_model.__tablename__):
        event.listen(_model.__table__, "after_create", DDL(_statement).execute_if(dialect="postgresql"))
