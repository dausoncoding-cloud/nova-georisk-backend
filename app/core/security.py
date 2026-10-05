"""Internal service authentication and trusted BFF principal context."""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from enum import Enum

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import get_settings


internal_secret_header = APIKeyHeader(name="X-Internal-Secret", auto_error=False)


async def verify_internal_secret(x_internal_secret: str | None = Security(internal_secret_header)) -> None:
    settings = get_settings()
    supplied = x_internal_secret or ""
    configured = settings.internal_api_secret or ""
    if not configured or not secrets.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Internal-Secret header.",
        )


class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


@dataclass(frozen=True)
class RequestContext:
    """Identity asserted by the trusted BFF after internal authentication."""

    user_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    role: OrganizationRole | None = None

    @property
    def is_service(self) -> bool:
        return self.user_id is None and self.organization_id is None


async def get_request_context(
    x_nova_user_id: str | None = Header(None, alias="X-Nova-User-Id", include_in_schema=False),
    x_nova_organization_id: str | None = Header(None, alias="X-Nova-Organization-Id", include_in_schema=False),
    x_nova_role: str | None = Header(None, alias="X-Nova-Role", include_in_schema=False),
) -> RequestContext:
    values = (x_nova_user_id, x_nova_organization_id, x_nova_role)
    if not any(values):
        return RequestContext()
    if not all(values):
        raise HTTPException(status_code=401, detail="Incomplete trusted principal context.")
    try:
        return RequestContext(
            user_id=uuid.UUID(x_nova_user_id),
            organization_id=uuid.UUID(x_nova_organization_id),
            role=OrganizationRole(x_nova_role),
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid trusted principal context.") from exc


def require_project_access(project, context: RequestContext) -> None:
    """Service callers retain compatibility; BFF callers are tenant-scoped."""
    if context.is_service:
        return
    if project.organization_id != context.organization_id:
        # Do not reveal that a project belonging to another tenant exists.
        raise HTTPException(status_code=404, detail="Project not found.")


def require_role(context: RequestContext, *allowed: OrganizationRole) -> None:
    if context.is_service:
        return
    if context.role not in allowed:
        raise HTTPException(status_code=403, detail="Insufficient organization permissions.")
