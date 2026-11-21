"""Abliner Mobile Money payments and integration status (docs/ABLINER_PAYMENTS_PLAN.md §11).

A payment intent is one "Pay with Mobile Money" action. It is never a payment: credits or a plan period are
recorded only when Abliner reports "completed", through the existing payments service (app/services/billing).
The full phone number is never stored: only a masked form and a SHA-256.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

OPEN_STATUSES = ("created", "pending", "pending_unknown")
STATUSES = (*OPEN_STATUSES, "completed", "failed", "expired", "review")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PaymentIntent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        CheckConstraint("purpose IN ('top_up','renewal')", name="ck_payment_intent_purpose"),
        CheckConstraint("status IN ('created','pending','pending_unknown','completed','failed','expired','review')",
                        name="ck_payment_intent_status"),
        CheckConstraint("amount > 0", name="ck_payment_intent_amount"),
        CheckConstraint("purpose <> 'top_up' OR (credits IS NOT NULL AND credits > 0)", name="ck_payment_intent_credits"),
        CheckConstraint("purpose <> 'renewal' OR (covers_from IS NOT NULL AND covers_until IS NOT NULL)",
                        name="ck_payment_intent_period"),
        # One open payment per subscription and purpose (prevents a second USSD prompt while one is pending).
        Index("uq_payment_intent_open", "subscription_id", "purpose", unique=True,
              postgresql_where=text("status IN ('created','pending','pending_unknown')")),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_subscriptions.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    covers_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    covers_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TZS")
    phone_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Our reference: Abliner's customer_reference, and the key we correlate webhooks and reconciliation on.
    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    # Sent as Idempotency-Key on POST /deposits; one per intent, never regenerated.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # The customer's own request key (browser IdempotentAction), so a double click creates one intent.
    request_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    abliner_tx_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    abliner_event_tx_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AblinerWebhookEvent(Base):
    """One row per received webhook (dedupe on its id). No raw body, no headers, no phone number."""

    __tablename__ = "abliner_webhook_events"

    webhook_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    event: Mapped[str | None] = mapped_column(String(60), nullable=True)
    abliner_tx_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    customer_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    remote_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    intent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)


class IntegrationStatus(Base):
    """Integrations page (read-only): last success, last error code, last webhook. Never a value or a payload."""

    __tablename__ = "integration_status"

    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_event: Mapped[str | None] = mapped_column(String(60), nullable=True)
