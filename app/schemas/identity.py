"""Browser-safe organization context and membership contracts."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.identity import MembershipRole


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None


class OrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class MembershipResponse(BaseModel):
    organization: OrganizationSummary
    role: MembershipRole
    created_at: datetime


class OrganizationContextResponse(BaseModel):
    user: CurrentUserResponse
    current_organization: OrganizationSummary
    current_role: MembershipRole
    memberships: list[MembershipResponse]
