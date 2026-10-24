"""Tenant-scoped role authority. Organization row locks serialize owner changes."""
import uuid,hashlib
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.entitlements import require_active_membership
from app.models.identity import Organization, OrganizationMembership, User, MembershipRole
from app.models.management import AccessAudit


def authorize(db, context, organization_id=None, *, lock=False):
    if context.is_service:
        raise HTTPException(403, 'A current organization user is required.')
    if organization_id is not None and organization_id != context.organization_id:
        raise HTTPException(404, 'Organization not found.')
    if lock:
        db.query(Organization).filter(Organization.id == context.organization_id).with_for_update().one()
        db.expire_all()
    membership = require_active_membership(db, context)
    if membership.role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
        raise HTTPException(403, 'Organization administration permission required.')
    return membership


def check_transition(actor_role, current_role, new_role, *, self_change=False):
    if self_change:
        raise HTTPException(403, 'Self-directed membership changes are not permitted.')
    if actor_role == MembershipRole.ADMIN and (current_role not in (None, MembershipRole.VIEWER, MembershipRole.ANALYST) or new_role not in (MembershipRole.VIEWER, MembershipRole.ANALYST)):
        raise HTTPException(403, 'Admins may manage viewer and analyst memberships only.')


def audit(db, context, request, action, previous, current, target=None):
    correlation = getattr(request.state, 'request_id', '')
    # Persist a bounded opaque correlation ID; never arbitrary header text.
    try: correlation = str(uuid.UUID(correlation))
    except (ValueError, TypeError): correlation = None
    db.add(AccessAudit(organization_id=context.organization_id, actor_user_id=context.user_id,
                       target_user_id=target, action=action, previous=previous, current=current, request_id=correlation))


def member_view(m):
    return dict(user_id=m.user_id, organization_id=m.organization_id, role=m.role, status=m.status,
                user_active=m.user.is_active, email=m.user.email, display_name=m.user.display_name,
                issuer=m.user.issuer, subject=m.user.subject, created_at=m.created_at, updated_at=m.updated_at)


def mutate(db, context, request, user, role, status, *, provision=False, evidence_reference=None):
    actor = authorize(db, context, lock=True)
    m = db.get(OrganizationMembership, (context.organization_id, user.id))
    if not provision and m is None:
        raise HTTPException(404, 'Membership not found.')
    check_transition(actor.role, m.role if m else None, role, self_change=user.id == context.user_id)
    if m and m.role == MembershipRole.OWNER and m.status == 'active' and (role != MembershipRole.OWNER or status != 'active'):
        owners = db.query(OrganizationMembership).join(User).filter(OrganizationMembership.organization_id==context.organization_id, OrganizationMembership.role==MembershipRole.OWNER, OrganizationMembership.status=='active', User.is_active.is_(True)).count()
        if owners <= 1:
            raise HTTPException(409, 'The final active owner cannot be demoted or removed.')
    previous = {'role': m.role.value, 'status': m.status} if m else None
    if m is None:
        m = OrganizationMembership(organization_id=context.organization_id, user_id=user.id, role=role, status=status)
        db.add(m)
    else: m.role, m.status = role, status
    current={'role':role.value,'status':status,'result':'applied'}
    if evidence_reference:current['identity_verification_reference_sha256']=hashlib.sha256(evidence_reference.encode()).hexdigest()
    audit(db, context, request, 'membership.provision' if provision else 'membership.change', previous, current, user.id)
    db.commit();db.refresh(m)
    return member_view(m)
