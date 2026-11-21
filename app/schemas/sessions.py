"""Device list and login history contracts. IP addresses are never returned to customers."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class DeviceSession(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    browser: str
    os: str
    device_type: str
    # Approximate (city-level, offline lookup); None when unknown.
    location: str | None
    country_code: str | None
    organization_name: str | None
    current: bool


class DeviceList(BaseModel):
    items: list[DeviceSession]
    # Active sessions allowed per user by the plan; None = no limit.
    session_limit: int | None
    # Attribution required by the GeoIP data licence, when locations are shown.
    location_attribution: str | None


class LoginHistoryEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    browser: str
    os: str
    device_type: str
    location: str | None
    country_code: str | None
    # active, signed_out, replaced (newer sign-in), ended_by_user, ended_by_admin or expired.
    result: str
    ended_at: datetime | None
    is_new_device: bool
    # Filled on the organisation view only.
    user_id: uuid.UUID | None = None
    user_display_name: str | None = None
    user_email: str | None = None


class LoginHistoryPage(BaseModel):
    items: list[LoginHistoryEntry]
    total: int
    limit: int
    offset: int


class SignOutOthersResponse(BaseModel):
    ended: int
