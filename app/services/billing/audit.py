"""Platform audit trail for NOVA ARI actions on customer accounts (plan section 8): reason required."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.billing import PlatformAudit

MAX_REASON = 2000


class ReasonRequired(ValueError):
    pass


@dataclass(frozen=True)
class Actor:
    """Who acted: a signed-in NOVA ARI admin (user ID and display name) or an operator command (label only)."""

    user_id: uuid.UUID | None
    label: str | None
    request_id: str | None = None

    @classmethod
    def command(cls, name: str) -> "Actor":
        return cls(user_id=None, label=f"operator command: {name}")


def require_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ReasonRequired("A reason is required.")
    if len(cleaned) > MAX_REASON:
        raise ReasonRequired(f"The reason must be at most {MAX_REASON} characters.")
    return cleaned


def record(
    db: Session,
    actor: Actor,
    action: str,
    *,
    reason: str,
    organization_id: uuid.UUID | None,
    target_type: str | None = None,
    target_id: object | None = None,
    previous: dict | None = None,
    current: dict | None = None,
) -> PlatformAudit:
    row = PlatformAudit(
        actor_user_id=actor.user_id, actor_label=actor.label, action=action, organization_id=organization_id,
        target_type=target_type, target_id=str(target_id) if target_id is not None else None,
        previous=previous, current=current, reason=require_reason(reason), request_id=actor.request_id,
    )
    db.add(row)
    db.flush()
    return row
