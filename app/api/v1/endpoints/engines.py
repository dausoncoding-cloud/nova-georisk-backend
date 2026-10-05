"""Platform engine discovery and read-only organization entitlement inspection."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.entitlements import (
    entitlement_is_active,
    require_active_membership,
)
from app.core.security import (
    OrganizationRole,
    RequestContext,
    get_request_context,
    require_role,
    verify_internal_secret,
)
from app.db.session import get_db
from app.models.identity import Organization
from app.models.platform import Engine, OrganizationEngineEntitlement
from app.schemas.platform import (
    EngineAccessResponse,
    OrganizationEntitlementPage,
    OrganizationEntitlementResponse,
)

router = APIRouter(tags=["Platform Engines"], dependencies=[Depends(verify_internal_secret)])


def _entitlement_response(
    entitlement: OrganizationEngineEntitlement,
) -> OrganizationEntitlementResponse:
    return OrganizationEntitlementResponse(
        id=entitlement.id,
        organization_id=entitlement.organization_id,
        engine_key=entitlement.engine_key,
        engine_name=entitlement.engine.name,
        status=entitlement.status,
        effective_access=entitlement.engine.enabled and entitlement_is_active(entitlement),
        starts_at=entitlement.starts_at,
        ends_at=entitlement.ends_at,
        trial_ends_at=entitlement.trial_ends_at,
        source=entitlement.source,
        subscription_id=entitlement.subscription_id,
        created_at=entitlement.created_at,
        updated_at=entitlement.updated_at,
    )


@router.get("/engines", response_model=list[EngineAccessResponse])
def list_available_engines(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> list[EngineAccessResponse]:
    if context.is_service:
        raise HTTPException(status_code=401, detail="Authenticated user context required.")
    require_active_membership(db, context)
    entitlements = (
        db.query(OrganizationEngineEntitlement)
        .options(joinedload(OrganizationEngineEntitlement.engine))
        .join(Engine, Engine.key == OrganizationEngineEntitlement.engine_key)
        .filter(
            OrganizationEngineEntitlement.organization_id == context.organization_id,
            Engine.enabled.is_(True),
        )
        .order_by(Engine.name)
        .all()
    )
    return [
        EngineAccessResponse(
            key=item.engine.key,
            name=item.engine.name,
            description=item.engine.description,
            status=item.engine.status,
            entitlement_status=item.status,
            version=item.engine.version,
            category=item.engine.category,
            route_namespace=item.engine.route_namespace,
            icon_identifier=item.engine.icon_identifier,
            capabilities=item.engine.capabilities,
        )
        for item in entitlements
        if entitlement_is_active(item)
    ]


@router.get(
    "/organizations/{organization_id}/engine-entitlements",
    response_model=OrganizationEntitlementPage,
)
def list_organization_entitlements(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> OrganizationEntitlementPage:
    if not context.is_service:
        require_active_membership(db, context)
        if context.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Organization not found.")
        require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN)
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    items = (
        db.query(OrganizationEngineEntitlement)
        .options(joinedload(OrganizationEngineEntitlement.engine))
        .filter(OrganizationEngineEntitlement.organization_id == organization_id)
        .order_by(OrganizationEngineEntitlement.engine_key)
        .all()
    )
    return OrganizationEntitlementPage(
        items=[_entitlement_response(item) for item in items], total=len(items)
    )
