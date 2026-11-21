"""One row per browser sign-in: the device list and the login history (plan section 6).

`session_hash` is the SHA-256 of the session cookie (the same digest the Redis session key uses); the
cookie itself is never stored. `ip_address` is removed after `session_ip_retention_days`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

END_REASONS = ("signed_out", "replaced", "ended_by_user", "ended_by_admin")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("end_reason IS NULL OR end_reason IN ('signed_out','replaced','ended_by_user','ended_by_admin')",
                        name="ck_user_session_end_reason"),
        CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="ck_user_session_ended"),
        Index("ix_user_sessions_user_created", "user_id", "created_at"),
        Index("ix_user_sessions_org_created", "organization_id", "created_at"),
    )

    # Also carried in the browser session as `session_ref`, so the API can tell "this device".
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                               nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The newer sign-in that ended this one (session limit).
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    browser: Mapped[str] = mapped_column(String(64), nullable=False)
    os: Mapped[str] = mapped_column(String(64), nullable=False)
    device_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # First sign-in of this user with this browser and OS (the admin console's "New device" flag).
    is_new_device: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
