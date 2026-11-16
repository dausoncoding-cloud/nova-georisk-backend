"""Area playground (P6): POST /api/v1/aois/capacity.

Internal API route (X-Internal-Secret), reached by browsers only through the BFF proxy like every other /api/v1
route. Organization-scoped (active membership, analyst or above, FRRIS entitlement), rate-limited per user and per
organization, pure geometry: no provider calls, nothing stored.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.entitlements import require_active_membership, require_engine_entitlement
from app.core.rate_limit import FixedWindowRateLimiter, get_preflight_limiter
from app.core.security import OrganizationRole, RequestContext, get_request_context, require_role, verify_internal_secret
from app.db.session import get_db
from app.schemas.aoi_capacity import AOICapacityRequest, AOICapacityResponse
from app.services.firris.aoi_capacity import assess_area

router = APIRouter(prefix="/aois", tags=["AOI"], dependencies=[Depends(verify_internal_secret)])


@router.post("/capacity", response_model=AOICapacityResponse)
def check_area_capacity(
    payload: AOICapacityRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
    limiter: FixedWindowRateLimiter = Depends(get_preflight_limiter),
) -> AOICapacityResponse:
    """Whether an area fits one FRRIS analysis (the preflight's capacity rule), with trim / split / coarser options."""
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    require_engine_entitlement(db, context, "firris")
    settings = get_settings()
    if not (limiter.allow(f"aoi:capacity:user:{context.user_id}", settings.aoi_capacity_per_user_per_minute)
            and limiter.allow(f"aoi:capacity:org:{context.organization_id}", settings.aoi_capacity_per_organization_per_minute)):
        raise HTTPException(status_code=429, detail="Too many area checks. Please wait a minute and try again.",
                            headers={"Retry-After": "60"})
    try:
        result = assess_area(payload.geometry.model_dump(), scale_m=payload.scale_m, trim_center=payload.trim_center)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AOICapacityResponse.model_validate(result)
