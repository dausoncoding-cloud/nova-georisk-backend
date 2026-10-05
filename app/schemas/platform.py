"""Browser-safe engine registry and organization entitlement contracts."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.platform import EntitlementStatus


class EngineAccessResponse(BaseModel):
    key: str
    name: str
    description: str
    status: str
    access: bool = True
    entitlement_status: EntitlementStatus
    version: str
    category: str
    route_namespace: str
    icon_identifier: str | None
    capabilities: dict = Field(default_factory=dict)


class OrganizationEntitlementResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    engine_key: str
    engine_name: str
    status: EntitlementStatus
    effective_access: bool
    starts_at: datetime | None
    ends_at: datetime | None
    trial_ends_at: datetime | None
    source: str
    subscription_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class OrganizationEntitlementPage(BaseModel):
    items: list[OrganizationEntitlementResponse]
    total: int
