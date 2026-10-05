"""Frontend-safe BFF authentication contracts."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AuthConfigResponse(BaseModel):
    method: str
    configured: bool
    message: str
    membership_policy: str = Field(serialization_alias="membershipPolicy")


class SessionUser(BaseModel):
    id: uuid.UUID
    display_name: str | None = Field(serialization_alias="displayName")
    email: str | None


class SessionOrganization(BaseModel):
    id: uuid.UUID
    name: str


class BrowserSessionResponse(BaseModel):
    authenticated: bool
    user: SessionUser | None
    organization: SessionOrganization | None
    roles: list[str]
    csrf_token: str | None = Field(serialization_alias="csrfToken")
