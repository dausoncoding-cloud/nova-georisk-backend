"""NOVA platform registry, billing-neutral subscriptions, and engine entitlements."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EntitlementStatus(str, enum.Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELED = "canceled"
    PENDING = "pending"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELED = "canceled"
    PENDING = "pending"


class Engine(TimestampMixin, Base):
    __tablename__ = "engines"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0")
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    route_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    icon_identifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    publicly_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subscription_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class BillingPlan(TimestampMixin, Base):
    """Price/currency-neutral product definition; checkout remains out of scope."""

    __tablename__ = "billing_plans"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    # Subscriptions (docs/PLATFORM_SUBSCRIPTIONS_PLAN.md section 2). Seeded from
    # app/services/billing/plans.v1.json; NULL limits on a custom plan come from the subscription.
    family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    seat_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    session_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_on_data_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # Internal plan (NOVAREX and the team's test organisation): not sold, hidden from customers.
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    unlimited_credits: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class BillingPlanEngine(Base):
    __tablename__ = "billing_plan_engines"

    plan_key: Mapped[str] = mapped_column(
        String(64), ForeignKey("billing_plans.key", ondelete="CASCADE"), primary_key=True
    )
    engine_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("engines.key", ondelete="CASCADE"), primary_key=True
    )
    usage_limits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class OrganizationSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    plan_key: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("billing_plans.key", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    # Subscriptions: one per organisation per plan family; per-contract overrides beat plan limits.
    family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    monthly_credits_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seat_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_bytes_override: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    session_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_on_data_failure_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # When `status` last changed (the Expired/Cancelled viewing grace counts from here).
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped[BillingPlan | None] = relationship()

    __table_args__ = (
        Index(
            "uq_subscription_org_family", "organization_id", "family", unique=True,
            postgresql_where=text("family IS NOT NULL"),
        ),
    )


class OrganizationEngineEntitlement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_engine_entitlements"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    engine_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("engines.key", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[EntitlementStatus] = mapped_column(Enum(EntitlementStatus), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    usage_limits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    engine: Mapped[Engine] = relationship()
    subscription: Mapped[OrganizationSubscription | None] = relationship()

    __table_args__ = (
        UniqueConstraint("organization_id", "engine_key", name="uq_org_engine_entitlement"),
    )
