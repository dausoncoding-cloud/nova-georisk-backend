"""Database-authoritative OIDC user and organization membership resolution."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.bff.oidc import OIDCClaims
from app.models.identity import (
    MembershipRole,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)


class MembershipResolutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResolvedMembership:
    user: User
    organization: Organization
    membership: OrganizationMembership


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _select_membership(
    memberships: list[OrganizationMembership], organization_id: uuid.UUID | None
) -> OrganizationMembership:
    if organization_id is not None:
        selected = next(
            (item for item in memberships if item.organization_id == organization_id), None
        )
        if selected is None:
            raise MembershipResolutionError(
                "membership_required", "No active membership exists for that organization."
            )
        return selected
    if not memberships:
        raise MembershipResolutionError(
            "membership_required", "An administrator must provision organization access."
        )
    if len(memberships) > 1:
        raise MembershipResolutionError(
            "organization_selection_required",
            "Select an organization before completing sign-in.",
        )
    return memberships[0]


def _existing_memberships(db: Session, user: User) -> list[OrganizationMembership]:
    return (
        db.query(OrganizationMembership)
        .options(joinedload(OrganizationMembership.organization))
        .filter(OrganizationMembership.user_id == user.id)
        .all()
    )


def _bootstrap_first_verified_user(
    db: Session,
    *,
    claims: OIDCClaims,
    bootstrap_organization_id: uuid.UUID,
    requested_organization_id: uuid.UUID | None,
) -> ResolvedMembership:
    """Atomically create the first non-production identity and owner membership."""
    if not claims.email or claims.email_verified is not True:
        raise MembershipResolutionError(
            "verified_email_required", "A verified email is required for bootstrap access."
        )
    if (
        requested_organization_id is not None
        and requested_organization_id != bootstrap_organization_id
    ):
        raise MembershipResolutionError(
            "membership_required", "No active membership exists for that organization."
        )

    # Every bootstrap attempt for this environment locks the same organization
    # row. Competing first logins therefore serialize before the global empty-
    # user check, and only one identity can become the bootstrap owner.
    organization = (
        db.query(Organization)
        .filter(Organization.id == bootstrap_organization_id)
        .with_for_update(of=Organization)
        .one_or_none()
    )
    if organization is None:
        raise MembershipResolutionError(
            "membership_required", "The bootstrap organization is not available."
        )

    # Recheck after acquiring the lock in case another callback completed while
    # this transaction waited.
    user = (
        db.query(User)
        .filter(User.issuer == claims.issuer, User.subject == claims.subject)
        .one_or_none()
    )
    if user is not None:
        if not user.is_active:
            raise MembershipResolutionError("account_disabled", "This account is disabled.")
        memberships = _existing_memberships(db, user)
        if memberships:
            membership = _select_membership(memberships, requested_organization_id)
            return ResolvedMembership(user, membership.organization, membership)
        raise MembershipResolutionError(
            "membership_required", "An administrator must provision organization access."
        )

    if db.query(User.id).limit(1).first() is not None:
        raise MembershipResolutionError(
            "membership_required", "An administrator must provision organization access."
        )

    user = User(
        issuer=claims.issuer,
        subject=claims.subject,
        email=claims.email,
        display_name=claims.display_name,
        is_active=True,
    )
    membership = OrganizationMembership(
        organization_id=organization.id,
        user=user,
        role=MembershipRole.OWNER,
    )
    db.add_all([user, membership])
    db.commit()
    db.refresh(user)
    db.refresh(membership)
    return ResolvedMembership(user, organization, membership)


def resolve_membership(
    db: Session,
    *,
    claims: OIDCClaims,
    policy: str,
    invitation_token: str | None,
    organization_id: uuid.UUID | None,
    bootstrap_first_user_enabled: bool = False,
    bootstrap_organization_id: uuid.UUID | None = None,
) -> ResolvedMembership:
    user = (
        db.query(User)
        .filter(User.issuer == claims.issuer, User.subject == claims.subject)
        .one_or_none()
    )
    if user is not None and not user.is_active:
        raise MembershipResolutionError("account_disabled", "This account is disabled.")

    if user is not None:
        memberships = _existing_memberships(db, user)
        if memberships and invitation_token is None:
            membership = _select_membership(memberships, organization_id)
            return ResolvedMembership(user, membership.organization, membership)

    if (
        user is None
        and invitation_token is None
        and bootstrap_first_user_enabled
        and bootstrap_organization_id is not None
    ):
        return _bootstrap_first_verified_user(
            db,
            claims=claims,
            bootstrap_organization_id=bootstrap_organization_id,
            requested_organization_id=organization_id,
        )

    if policy.lower() != "optional_invite" or not invitation_token:
        raise MembershipResolutionError(
            "membership_required", "An administrator must provision organization access."
        )
    if not claims.email or claims.email_verified is not True:
        raise MembershipResolutionError(
            "verified_email_required", "A verified email is required to activate an invitation."
        )

    token_hash = invitation_token_hash(invitation_token)
    invitation = (
        db.query(OrganizationInvitation)
        .filter(OrganizationInvitation.token_hash == token_hash)
        # Lock only the invitation row. Eager-loading the organization here
        # adds a LEFT OUTER JOIN, and PostgreSQL cannot apply FOR UPDATE to the
        # nullable side of that join. The row lock is held through the commit
        # below, preserving atomic, single-use invitation consumption.
        .with_for_update(of=OrganizationInvitation)
        .one_or_none()
    )
    now = datetime.now(timezone.utc)
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.expires_at <= now
        or not secrets.compare_digest(invitation.email.casefold(), claims.email.casefold())
        or (organization_id is not None and invitation.organization_id != organization_id)
    ):
        raise MembershipResolutionError(
            "invalid_invitation", "The invitation is invalid, expired, or already used."
        )

    organization = db.get(Organization, invitation.organization_id)
    if organization is None:
        raise MembershipResolutionError(
            "invalid_invitation", "The invitation is invalid, expired, or already used."
        )

    if user is None:
        user = User(
            issuer=claims.issuer,
            subject=claims.subject,
            email=claims.email,
            display_name=claims.display_name,
            is_active=True,
        )
        db.add(user)
        db.flush()
    existing = db.get(OrganizationMembership, (invitation.organization_id, user.id))
    if existing is not None:
        raise MembershipResolutionError(
            "invalid_invitation", "The invitation cannot create a duplicate membership."
        )
    membership = OrganizationMembership(
        organization_id=invitation.organization_id,
        user_id=user.id,
        role=invitation.role,
    )
    invitation.accepted_at = now
    db.add(membership)
    db.commit()
    db.refresh(user)
    db.refresh(membership)
    return ResolvedMembership(user, organization, membership)
