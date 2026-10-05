"""Distinct membership, engine-entitlement, and role authorization checks."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import OrganizationRole, RequestContext, get_request_context, require_role
from app.db.session import get_db
from app.models.identity import OrganizationMembership, User
from app.models.platform import Engine, EntitlementStatus, OrganizationEngineEntitlement


def require_active_membership(
    db: Session, context: RequestContext
) -> OrganizationMembership | None:
    """Revalidate session membership so revocation does not wait for cookie expiry."""
    if context.is_service:
        return None
    user = db.get(User, context.user_id)
    membership = db.get(
        OrganizationMembership, (context.organization_id, context.user_id)
    )
    if user is None or not user.is_active or membership is None:
        raise HTTPException(status_code=403, detail="Active organization membership required.")
    if membership.role.value != context.role.value:
        raise HTTPException(status_code=403, detail="Session permissions have changed; sign in again.")
    return membership


def entitlement_is_active(
    entitlement: OrganizationEngineEntitlement, at: datetime | None = None
) -> bool:
    at = at or datetime.now(timezone.utc)
    if entitlement.status not in {EntitlementStatus.ACTIVE, EntitlementStatus.TRIAL}:
        return False
    if entitlement.starts_at is not None and entitlement.starts_at > at:
        return False
    if entitlement.ends_at is not None and entitlement.ends_at <= at:
        return False
    if entitlement.status == EntitlementStatus.TRIAL:
        return entitlement.trial_ends_at is not None and entitlement.trial_ends_at > at
    return True


def require_engine_entitlement(
    db: Session,
    context: RequestContext,
    engine_key: str,
) -> OrganizationEngineEntitlement | None:
    """Require current NOVA DB entitlement; provider claims are never consulted."""
    if context.is_service:
        return None
    engine = db.get(Engine, engine_key)
    if engine is None or not engine.enabled:
        raise HTTPException(status_code=403, detail="Engine access is unavailable.")
    entitlement = (
        db.query(OrganizationEngineEntitlement)
        .filter(
            OrganizationEngineEntitlement.organization_id == context.organization_id,
            OrganizationEngineEntitlement.engine_key == engine_key,
        )
        .one_or_none()
    )
    if entitlement is None or not entitlement_is_active(entitlement):
        raise HTTPException(status_code=403, detail="Engine access is unavailable.")
    return entitlement


def active_engine_keys(db: Session, organization_id: uuid.UUID) -> set[str]:
    entitlements = (
        db.query(OrganizationEngineEntitlement)
        .join(Engine, Engine.key == OrganizationEngineEntitlement.engine_key)
        .filter(
            OrganizationEngineEntitlement.organization_id == organization_id,
            Engine.enabled.is_(True),
        )
        .all()
    )
    return {
        entitlement.engine_key
        for entitlement in entitlements
        if entitlement_is_active(entitlement)
    }


def require_current_engine(
    engine_key: str,
    *roles: OrganizationRole,
) -> Callable:
    """FastAPI dependency for legacy non-project FIRRIS calculators."""

    def dependency(
        db: Session = Depends(get_db),
        context: RequestContext = Depends(get_request_context),
    ) -> None:
        require_active_membership(db, context)
        require_engine_entitlement(db, context, engine_key)
        if roles:
            require_role(context, *roles)

    return dependency
