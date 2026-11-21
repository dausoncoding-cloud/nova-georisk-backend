"""NOVA ARI platform administration (plan section 8): operator grants, security alerts, daily usage.

`platform_admins` is written only by the deploy-time command (`python -m app.services.platform_admin.cli`);
no API route writes it. A revoked grant keeps its row (revoked_at), and both actions are in platform_audit.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlatformAdmin(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "platform_admins"
    __table_args__ = (
        # At most one live grant per user; history stays as revoked rows.
        Index("uq_platform_admin_live", "user_id", unique=True, postgresql_where=text("revoked_at IS NULL")),
        CheckConstraint("length(trim(reason)) > 0", name="ck_platform_admin_reason"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    granted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SecurityAlert(UUIDPrimaryKeyMixin, Base):
    """Raised by the platform, reviewed by NOVA ARI. v1 has one kind: a sign-in from a browser and OS
    this user has not used before. (Automatic account-sharing detection is a later option.)"""

    __tablename__ = "security_alerts"
    __table_args__ = (
        CheckConstraint("kind IN ('new_device')", name="ck_security_alert_kind"),
        CheckConstraint("(acknowledged_at IS NULL) = (acknowledge_reason IS NULL)", name="ck_security_alert_ack"),
        Index("ix_security_alerts_open", "organization_id", postgresql_where=text("acknowledged_at IS NULL")),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                               nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    # Browser, OS, approximate location: never the IP address.
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrganizationUsageDaily(Base):
    """Per organisation per day (billing timezone): API requests and downloads. Counted in Redis on the
    request path and flushed here (Redis is not persistent in this deployment)."""

    __tablename__ = "organization_usage_daily"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    api_requests: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    downloads: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    download_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))


class SubscriptionRequest(UUIDPrimaryKeyMixin, Base):
    """"Request top-up" and "Request upgrade" from the customer's My subscription page (no payment in the
    app). NOVA ARI closes each one with an outcome and a reason (audited)."""

    __tablename__ = "subscription_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('top_up','upgrade')", name="ck_subscription_request_kind"),
        CheckConstraint("status IN ('open','done','declined')", name="ck_subscription_request_status"),
        CheckConstraint("kind <> 'upgrade' OR plan_key IS NOT NULL", name="ck_subscription_request_plan"),
        CheckConstraint("kind <> 'top_up' OR (credits IS NOT NULL AND credits > 0)", name="ck_subscription_request_credits"),
        CheckConstraint("(status = 'open') = (closed_at IS NULL)", name="ck_subscription_request_closed"),
        # One open request per kind per subscription: asking again returns the open one.
        Index("uq_subscription_request_open", "subscription_id", "kind", unique=True,
              postgresql_where=text("status = 'open'")),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_subscriptions.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    plan_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credits: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
