"""Explicit administrator provisioning for OIDC identities and invitations."""
from __future__ import annotations

import argparse
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.bff.membership import invitation_token_hash
from app.db.session import SessionLocal
from app.models.identity import (
    MembershipRole,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    create_org = commands.add_parser("create-organization")
    create_org.add_argument("--name", required=True)
    create_org.add_argument("--slug", required=True)

    create_user = commands.add_parser("create-user")
    create_user.add_argument("--issuer", required=True)
    create_user.add_argument("--subject", required=True)
    create_user.add_argument("--email")
    create_user.add_argument("--display-name")

    grant = commands.add_parser("grant-membership")
    grant.add_argument("--user-id", required=True, type=uuid.UUID)
    grant.add_argument("--organization-id", required=True, type=uuid.UUID)
    grant.add_argument("--role", required=True, choices=[role.value for role in MembershipRole])

    invite = commands.add_parser("issue-invitation")
    invite.add_argument("--organization-id", required=True, type=uuid.UUID)
    invite.add_argument("--email", required=True)
    invite.add_argument("--role", required=True, choices=[role.value for role in MembershipRole])
    invite.add_argument("--hours", type=int, default=72)
    return root


def main() -> None:
    args = parser().parse_args()
    with SessionLocal() as db:
        if args.command == "create-organization":
            organization = Organization(name=args.name, slug=args.slug)
            db.add(organization)
            db.commit()
            print(f"created organization id={organization.id} slug={organization.slug}")
            return
        if args.command == "create-user":
            user = User(
                issuer=args.issuer,
                subject=args.subject,
                email=args.email.casefold() if args.email else None,
                display_name=args.display_name,
                is_active=True,
            )
            db.add(user)
            db.commit()
            print(f"created user id={user.id} issuer={user.issuer} subject={user.subject}")
            return

        organization = db.get(Organization, args.organization_id)
        if organization is None:
            raise SystemExit("Organization not found; no changes committed.")
        if args.command == "grant-membership":
            user = db.get(User, args.user_id)
            if user is None:
                raise SystemExit("User not found; no changes committed.")
            if db.get(OrganizationMembership, (organization.id, user.id)) is not None:
                raise SystemExit("Membership already exists; no changes committed.")
            membership = OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=MembershipRole(args.role),
            )
            db.add(membership)
            db.commit()
            print(
                f"granted role={args.role} user_id={user.id} organization_id={organization.id}"
            )
            return

        if args.hours < 1 or args.hours > 720:
            raise SystemExit("--hours must be between 1 and 720.")
        token = secrets.token_urlsafe(32)
        invitation = OrganizationInvitation(
            organization_id=organization.id,
            email=args.email.strip().casefold(),
            role=MembershipRole(args.role),
            token_hash=invitation_token_hash(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=args.hours),
        )
        db.add(invitation)
        db.commit()
        print(
            f"issued invitation id={invitation.id} organization_id={organization.id} "
            f"expires_at={invitation.expires_at.isoformat()}"
        )
        print(f"invitation_token={token}")
        print("Store this token securely; only its SHA-256 digest is persisted.")


if __name__ == "__main__":
    main()
