"""Authenticated organization context for the browser application."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.entitlements import require_active_membership
from app.core.security import RequestContext, get_request_context, verify_internal_secret
from app.db.session import get_db
from app.models.identity import OrganizationMembership, User
from app.schemas.identity import (
    CurrentUserResponse,
    MembershipResponse,
    OrganizationContextResponse,
    OrganizationSummary,
)

router = APIRouter(
    prefix="/organizations",
    tags=["Organizations"],
    dependencies=[Depends(verify_internal_secret)],
)


@router.get("/current", response_model=OrganizationContextResponse)
def get_current_organization_context(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> OrganizationContextResponse:
    """Return the selected organization plus all memberships owned by this user."""
    if context.is_service:
        raise HTTPException(status_code=401, detail="Authenticated user context required.")
    current_membership = require_active_membership(db, context)
    user = db.get(User, context.user_id)
    if user is None or current_membership is None:
        raise HTTPException(status_code=403, detail="Active organization membership required.")

    memberships = (
        db.query(OrganizationMembership)
        .options(joinedload(OrganizationMembership.organization))
        .filter(OrganizationMembership.user_id == user.id)
        .join(OrganizationMembership.organization)
        .order_by(OrganizationMembership.organization_id)
        .all()
    )
    current_organization = current_membership.organization
    return OrganizationContextResponse(
        user=CurrentUserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
        ),
        current_organization=OrganizationSummary(
            id=current_organization.id,
            name=current_organization.name,
            slug=current_organization.slug,
        ),
        current_role=current_membership.role,
        memberships=[
            MembershipResponse(
                organization=OrganizationSummary(
                    id=membership.organization.id,
                    name=membership.organization.name,
                    slug=membership.organization.slug,
                ),
                role=membership.role,
                created_at=membership.created_at,
            )
            for membership in memberships
        ],
    )
