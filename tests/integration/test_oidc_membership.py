import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.bff.membership import (
    MembershipResolutionError,
    invitation_token_hash,
    resolve_membership,
)
from app.bff.oidc import OIDCClaims
from app.models.identity import (
    LEGACY_ORGANIZATION_ID,
    MembershipRole,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)


def _claims(subject="subject-1", email="user@example.com", verified=True):
    return OIDCClaims(
        issuer="https://identity.example.com",
        subject=subject,
        email=email,
        email_verified=verified,
        display_name="Example User",
    )


def test_strict_policy_resolves_only_preprovisioned_membership(db_session):
    organization = Organization(name="Strict Org", slug="strict-org")
    user = User(
        issuer="https://identity.example.com",
        subject="subject-1",
        email="user@example.com",
        is_active=True,
    )
    db_session.add_all([organization, user])
    db_session.flush()
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role=MembershipRole.ANALYST,
    )
    db_session.add(membership)
    db_session.commit()

    resolved = resolve_membership(
        db_session,
        claims=_claims(),
        policy="strict",
        invitation_token=None,
        organization_id=None,
    )
    assert resolved.organization.id == organization.id
    assert resolved.membership.role == MembershipRole.ANALYST


def test_strict_policy_rejects_unknown_identity(db_session):
    with pytest.raises(MembershipResolutionError) as caught:
        resolve_membership(
            db_session,
            claims=_claims(subject="unknown"),
            policy="strict",
            invitation_token=None,
            organization_id=None,
        )
    assert caught.value.code == "membership_required"
    assert db_session.query(User).count() == 0


def test_first_verified_oidc_login_bootstraps_owner_in_non_production(db_session):
    organization = Organization(
        id=LEGACY_ORGANIZATION_ID,
        name="Legacy organization",
        slug="legacy",
    )
    db_session.add(organization)
    db_session.commit()

    resolved = resolve_membership(
        db_session,
        claims=_claims(),
        policy="strict",
        invitation_token=None,
        organization_id=None,
        bootstrap_first_user_enabled=True,
        bootstrap_organization_id=organization.id,
    )

    persisted_user = (
        db_session.query(User)
        .filter(
            User.issuer == "https://identity.example.com",
            User.subject == "subject-1",
        )
        .one()
    )
    assert persisted_user.id == resolved.user.id
    assert persisted_user.email == "user@example.com"
    assert persisted_user.display_name == "Example User"
    assert resolved.organization.id == organization.id
    assert resolved.membership.role == MembershipRole.OWNER
    assert db_session.get(
        OrganizationMembership, (organization.id, persisted_user.id)
    ) is not None


def test_bootstrap_does_not_reenable_existing_disabled_user(db_session):
    organization = Organization(
        id=LEGACY_ORGANIZATION_ID,
        name="Legacy organization",
        slug="legacy",
    )
    user = User(
        issuer="https://identity.example.com",
        subject="subject-1",
        email="user@example.com",
        is_active=False,
    )
    db_session.add_all([organization, user])
    db_session.commit()

    with pytest.raises(MembershipResolutionError) as caught:
        resolve_membership(
            db_session,
            claims=_claims(),
            policy="strict",
            invitation_token=None,
            organization_id=None,
            bootstrap_first_user_enabled=True,
            bootstrap_organization_id=organization.id,
        )
    assert caught.value.code == "account_disabled"


def test_bootstrap_never_grants_a_second_unprovisioned_identity(db_session):
    organization = Organization(
        id=LEGACY_ORGANIZATION_ID,
        name="Legacy organization",
        slug="legacy",
    )
    existing_user = User(
        issuer="https://identity.example.com",
        subject="existing",
        email="existing@example.com",
        is_active=True,
    )
    db_session.add_all([organization, existing_user])
    db_session.commit()

    with pytest.raises(MembershipResolutionError) as caught:
        resolve_membership(
            db_session,
            claims=_claims(subject="second-user"),
            policy="strict",
            invitation_token=None,
            organization_id=None,
            bootstrap_first_user_enabled=True,
            bootstrap_organization_id=organization.id,
        )
    assert caught.value.code == "membership_required"
    assert db_session.query(User).count() == 1


def test_optional_invite_requires_verified_matching_email_and_is_single_use(db_session):
    organization = Organization(name="Invite Org", slug="invite-org")
    db_session.add(organization)
    db_session.flush()
    token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        organization_id=organization.id,
        email="user@example.com",
        role=MembershipRole.VIEWER,
        token_hash=invitation_token_hash(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(invitation)
    db_session.commit()

    resolved = resolve_membership(
        db_session,
        claims=_claims(),
        policy="optional_invite",
        invitation_token=token,
        organization_id=organization.id,
    )
    assert resolved.membership.role == MembershipRole.VIEWER
    assert invitation.accepted_at is not None

    with pytest.raises(MembershipResolutionError) as replay:
        resolve_membership(
            db_session,
            claims=_claims(),
            policy="optional_invite",
            invitation_token=token,
            organization_id=organization.id,
        )
    assert replay.value.code == "invalid_invitation"
