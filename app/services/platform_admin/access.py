"""The `nova_ari_admin` platform role (plan section 8).

- Granted to named users only by the deploy-time command (`cli.py`); no API route grants or revokes it.
- Checked server-side on every /api/v1/platform-admin request (`require_platform_admin`), from the
  database each time: a revoked grant or a disabled user stops working on the next request.
- It is not an organisation role, and no organisation route reads it, so it gives no cross-organisation
  access anywhere else.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.entitlements import require_active_membership
from app.core.http import PublicAPIError
from app.core.security import RequestContext, get_request_context
from app.db.session import get_db
from app.models.identity import Organization, User
from app.models.platform_admin import PlatformAdmin
from app.services.billing import audit


@dataclass(frozen=True)
class AdminContext:
    user_id: uuid.UUID
    display_name: str
    email: str | None
    organization_name: str | None
    request_id: str | None

    @property
    def actor(self) -> audit.Actor:
        return audit.Actor(user_id=self.user_id, label=self.display_name, request_id=self.request_id)


def live_grant(db: Session, user_id: uuid.UUID) -> PlatformAdmin | None:
    return (db.query(PlatformAdmin)
            .filter(PlatformAdmin.user_id == user_id, PlatformAdmin.revoked_at.is_(None))
            .one_or_none())


def _forbidden() -> PublicAPIError:
    return PublicAPIError(403, "platform_admin_required", "NOVA ARI administration access is required.")


def require_platform_admin(
    request: Request,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AdminContext:
    if context.is_service:
        raise _forbidden()
    require_active_membership(db, context)  # a current, active user with a valid session principal
    if live_grant(db, context.user_id) is None:
        raise _forbidden()
    user = db.get(User, context.user_id)
    organization = db.get(Organization, context.organization_id)
    request_id = getattr(request.state, "request_id", None)
    try:
        request_id = str(uuid.UUID(request_id)) if request_id else None
    except ValueError:
        request_id = None
    return AdminContext(user_id=user.id, display_name=user.display_name or user.email or str(user.id),
                        email=user.email, organization_name=organization.name if organization else None,
                        request_id=request_id)


# --- used only by the deploy-time command ------------------------------------------------------------

class GrantError(ValueError):
    pass


def _find_user(db: Session, *, email: str | None, user_id: uuid.UUID | None) -> User:
    if user_id is not None:
        user = db.get(User, user_id)
    else:
        matches = db.query(User).filter(User.email.ilike((email or "").strip())).all()
        if len(matches) > 1:
            raise GrantError("More than one user has this email; use --user-id.")
        user = matches[0] if matches else None
    if user is None:
        raise GrantError("User not found. The person must have signed in once first.")
    if not user.is_active:
        raise GrantError("This user is disabled.")
    return user


def grant(db: Session, *, email: str | None, user_id: uuid.UUID | None, reason: str, operator: str) -> PlatformAdmin:
    reason = audit.require_reason(reason)
    user = _find_user(db, email=email, user_id=user_id)
    if live_grant(db, user.id) is not None:
        raise GrantError("This user is already a NOVA ARI admin.")
    row = PlatformAdmin(user_id=user.id, granted_by=operator, reason=reason)
    db.add(row)
    db.flush()
    audit.record(db, audit.Actor.command(f"platform-admin grant ({operator})"), "platform_admin.grant", reason=reason,
                 organization_id=None, target_type="user", target_id=user.id,
                 current={"user_id": str(user.id), "email": user.email})
    return row


def revoke(db: Session, *, email: str | None, user_id: uuid.UUID | None, reason: str, operator: str) -> PlatformAdmin:
    reason = audit.require_reason(reason)
    user = _find_user(db, email=email, user_id=user_id) if user_id or email else None
    row = live_grant(db, user.id) if user else None
    if row is None:
        raise GrantError("This user is not a NOVA ARI admin.")
    row.revoked_at, row.revoke_reason = datetime.now(timezone.utc), reason
    db.flush()
    audit.record(db, audit.Actor.command(f"platform-admin revoke ({operator})"), "platform_admin.revoke",
                 reason=reason, organization_id=None, target_type="user", target_id=user.id,
                 previous={"granted_at": row.granted_at.isoformat()})
    return row
