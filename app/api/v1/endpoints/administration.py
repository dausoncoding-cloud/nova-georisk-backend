import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.security import verify_internal_secret, get_request_context, RequestContext
from app.core.config import get_settings
from app.db.session import get_db
from app.models.identity import OrganizationMembership, OrganizationInvitation, User
from app.models.management import AccessAudit
from app.schemas.management import MemberPage, MemberView, ProvisionMembership, MembershipChange, AuditPage, InvitationView
from app.services.access_management import authorize, mutate, member_view, check_transition

router=APIRouter(prefix='/organizations/{organization_id}/administration', tags=['Administration'], dependencies=[Depends(verify_internal_secret)])

@router.get('/memberships', response_model=MemberPage)
def members(organization_id: uuid.UUID, q: str=Query('',max_length=100), status: str|None=None, role: str|None=None, offset:int=Query(0,ge=0), limit:int=Query(25,ge=1,le=100), db:Session=Depends(get_db), context:RequestContext=Depends(get_request_context)):
    authorize(db,context,organization_id)
    query=db.query(OrganizationMembership).join(User).filter(OrganizationMembership.organization_id==organization_id)
    if q:query=query.filter(or_(User.email.ilike('%'+q+'%'),User.display_name.ilike('%'+q+'%'),User.subject.ilike('%'+q+'%')))
    if status:query=query.filter(OrganizationMembership.status==status)
    if role:
        from app.models.identity import MembershipRole
        try: value=MembershipRole(role)
        except ValueError:raise HTTPException(422,'Invalid membership role.')
        query=query.filter(OrganizationMembership.role==value)
    return {'total':query.count(),'items':[member_view(m) for m in query.order_by(OrganizationMembership.created_at,OrganizationMembership.user_id).offset(offset).limit(limit).all()]}

@router.post('/memberships',response_model=MemberView,status_code=201)
def provision(organization_id:uuid.UUID, body:ProvisionMembership,request:Request,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    actor=authorize(db,context,organization_id,lock=True)
    check_transition(actor.role,None,body.role)
    issuer=get_settings().oidc_issuer_url
    if not issuer or body.issuer != issuer:raise HTTPException(422,'Use the exact configured OIDC issuer and provider-verified subject.')
    user=db.query(User).filter(User.issuer==body.issuer,User.subject==body.subject).one_or_none()
    if user is None:
        user=User(issuer=body.issuer,subject=body.subject,email=body.email,display_name=body.display_name,is_active=True)
        db.add(user)
        try:db.flush()
        except IntegrityError:
            db.rollback();raise HTTPException(409,"Identity provisioning raced with another request; retry.") from None
    # Identity fields of an existing user are never overwritten by organization admins.
    return mutate(db,context,request,user,body.role,'active',provision=True,evidence_reference=body.evidence_reference)

@router.patch('/memberships/{user_id}',response_model=MemberView)
def change(organization_id:uuid.UUID,user_id:uuid.UUID,body:MembershipChange,request:Request,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    authorize(db,context,organization_id)
    user=db.get(User,user_id)
    if user is None:raise HTTPException(404,'Membership not found.')
    return mutate(db,context,request,user,body.role,body.status)

@router.get('/audit',response_model=AuditPage)
def events(organization_id:uuid.UUID,user_id:uuid.UUID|None=None,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)):
    authorize(db,context,organization_id)
    query=db.query(AccessAudit).filter(AccessAudit.organization_id==organization_id)
    if user_id:query=query.filter(AccessAudit.target_user_id==user_id)
    return {'total':query.count(),'items':query.order_by(AccessAudit.created_at.desc(),AccessAudit.id).offset(offset).limit(limit).all()}

@router.get('/invitations',response_model=list[InvitationView])
def invitations(organization_id:uuid.UUID,db:Session=Depends(get_db),context:RequestContext=Depends(get_request_context)) -> list[dict]:
    authorize(db,context,organization_id)
    now=datetime.now(timezone.utc)
    return [dict(id=str(i.id),email=i.email,role=i.role.value,created_at=i.created_at,expires_at=i.expires_at,status='redeemed' if i.accepted_at else 'expired' if i.expires_at<=now else 'pending',access_granted=None if i.accepted_at else False,policy_note='Strict policy requires explicit membership provisioning; pending invitations do not grant access.') for i in db.query(OrganizationInvitation).filter(OrganizationInvitation.organization_id==organization_id).order_by(OrganizationInvitation.created_at.desc()).limit(100).all()]
