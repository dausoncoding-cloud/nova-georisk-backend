"""Account statuses (plan section 5).

| Status    | Sign in | View and download            | New analyses              |
|-----------|---------|------------------------------|---------------------------|
| Active    | yes     | yes                          | yes, while credits remain |
| Suspended | yes     | yes                          | no                        |
| Expired   | yes     | yes, for the grace period    | no                        |
| Cancelled | yes     | yes, for the grace period    | no                        |

Engine entitlements are what gate viewing and downloads (`require_engine_entitlement`), so a status
change leaves them alone and only the submission check (`submission.block_code`) refuses new analyses.
The one exception is the Q7 grace period: once an Expired or Cancelled subscription has been in that
status longer than `billing_view_grace_days`, `sweep` closes its entitlements. Reactivation reopens exactly
the entitlements the sweep closed. Security review H1: the grace applies only while billing enforcement is on and
the setting is set (unset by default; the owner sets it at Phase B). With enforcement off nothing closes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.platform import EntitlementStatus, OrganizationEngineEntitlement, OrganizationSubscription, SubscriptionStatus
from app.services.billing import audit, ledger

GRACE_CLOSED_BY = "billing_grace"
_UNSET = object()


class StatusError(ValueError):
    pass


def _view(subscription: OrganizationSubscription) -> dict:
    return {"status": subscription.status.value,
            "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None}


def _linked_entitlements(db: Session, subscription: OrganizationSubscription) -> list[OrganizationEngineEntitlement]:
    return (
        db.query(OrganizationEngineEntitlement)
        .filter(OrganizationEngineEntitlement.subscription_id == subscription.id)
        .order_by(OrganizationEngineEntitlement.engine_key)
        .all()
    )


def _reopen_grace_closed(db: Session, subscription: OrganizationSubscription) -> list[str]:
    reopened = []
    for entitlement in _linked_entitlements(db, subscription):
        metadata = dict(entitlement.metadata_json or {})
        if entitlement.status == EntitlementStatus.EXPIRED and metadata.get("closed_by") == GRACE_CLOSED_BY:
            metadata.pop("closed_by", None)
            metadata.pop("closed_at", None)
            entitlement.status = EntitlementStatus.ACTIVE
            entitlement.metadata_json = metadata or None
            reopened.append(entitlement.engine_key)
    return reopened


def change_status(
    db: Session,
    subscription_id: uuid.UUID,
    new_status: SubscriptionStatus | str,
    *,
    reason: str,
    actor: audit.Actor,
    ends_at: datetime | None | object = _UNSET,
    action: str = "subscription.status",
) -> OrganizationSubscription:
    """Set the status (and optionally the end date) with a reason; writes `platform_audit`. Takes the
    subscription row lock; the caller commits."""
    reason = audit.require_reason(reason)
    new_status = SubscriptionStatus(new_status)
    subscription = ledger.lock_subscription(db, subscription_id)
    previous = _view(subscription)
    if new_status == subscription.status and (ends_at is _UNSET or ends_at == subscription.ends_at):
        raise StatusError(f"The subscription is already {new_status.value}.")
    now = datetime.now(timezone.utc)
    if ends_at is not _UNSET:
        subscription.ends_at = ends_at
    if new_status == SubscriptionStatus.ACTIVE and subscription.ends_at is not None and subscription.ends_at <= now:
        raise StatusError("Set an end date in the future (or none) to reactivate this subscription.")
    if new_status != subscription.status:
        subscription.status = new_status
        subscription.status_changed_at = now
    current = _view(subscription)
    if new_status == SubscriptionStatus.ACTIVE:
        reopened = _reopen_grace_closed(db, subscription)
        if reopened:
            current["entitlements_reopened"] = reopened
    db.flush()
    audit.record(db, actor, action, reason=reason, organization_id=subscription.organization_id,
                 target_type="subscription", target_id=subscription.id, previous=previous, current=current)
    return subscription


def grace_days_in_force() -> int | None:
    """H1: the Q7 viewing grace, or None when viewing never closes (setting unset, or billing enforcement off)."""
    settings = get_settings()
    if not settings.billing_enforcement_enabled:
        return None
    return settings.billing_view_grace_days


def access_ends_at(subscription: OrganizationSubscription) -> datetime | None:
    """Q7: when viewing and downloads close for an Expired or Cancelled subscription (None: not ending)."""
    grace_days = grace_days_in_force()
    if grace_days is None or subscription.status not in {SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELED}:
        return None
    since = subscription.status_changed_at or subscription.ends_at
    return since + timedelta(days=grace_days) if since else None


def sweep(db: Session, *, apply: bool, actor: audit.Actor, now: datetime | None = None) -> list[dict]:
    """Automatic status rules, for the operator command (dry run unless `apply`):
    1. an Active or Trial subscription past its end (or trial end) becomes Expired;
    2. with `billing_view_grace_days` set AND billing enforcement on (H1), an Expired or Cancelled subscription
       older than the grace period has its linked entitlements closed, which ends viewing and downloads.
    """
    now = now or datetime.now(timezone.utc)
    actions: list[dict] = []
    candidates = (
        db.query(OrganizationSubscription.id)
        .filter(OrganizationSubscription.family.isnot(None))
        .order_by(OrganizationSubscription.organization_id, OrganizationSubscription.family)
        .all()
    )
    grace_days = grace_days_in_force()
    for (subscription_id,) in candidates:
        subscription = db.get(OrganizationSubscription, subscription_id)
        ended = subscription.ends_at is not None and subscription.ends_at <= now
        trial_ended = (subscription.status == SubscriptionStatus.TRIAL
                       and (subscription.trial_ends_at is None or subscription.trial_ends_at <= now))
        if subscription.status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL} and (ended or trial_ended):
            actions.append({"action": "expire", "organization_id": str(subscription.organization_id),
                            "subscription_id": str(subscription.id), "family": subscription.family})
            if apply:
                change_status(db, subscription.id, SubscriptionStatus.EXPIRED, actor=actor,
                              reason="The subscription period ended without renewal.", action="subscription.expire")
            continue
        if grace_days is None or subscription.status not in {SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELED}:
            continue
        since = subscription.status_changed_at or subscription.ends_at
        if since is None or since + timedelta(days=grace_days) > now:
            continue
        open_items = [item for item in _linked_entitlements(db, subscription)
                      if item.status in {EntitlementStatus.ACTIVE, EntitlementStatus.TRIAL}]
        if not open_items:
            continue
        engines = [item.engine_key for item in open_items]
        actions.append({"action": "close_entitlements", "organization_id": str(subscription.organization_id),
                        "subscription_id": str(subscription.id), "family": subscription.family, "engines": engines})
        if apply:
            ledger.lock_subscription(db, subscription.id)
            for item in open_items:
                item.metadata_json = {**(item.metadata_json or {}), "closed_by": GRACE_CLOSED_BY,
                                      "closed_at": now.isoformat()}
                item.status = EntitlementStatus.EXPIRED
            db.flush()
            audit.record(db, actor, "subscription.grace_ended", organization_id=subscription.organization_id,
                         reason=f"Viewing grace of {grace_days} days ended after {subscription.status.value}.",
                         target_type="subscription", target_id=subscription.id,
                         previous={"entitlements": {engine: "active" for engine in engines}},
                         current={"entitlements": {engine: "expired" for engine in engines}})
    return actions
