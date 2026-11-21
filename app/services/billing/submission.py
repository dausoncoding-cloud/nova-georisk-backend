"""Credit and status checks for the three submission paths (submit, source-bound, retry).

Order inside one database transaction, after `admit_task` (which holds the organisation's admission lock):
  1. `replay_or_none`  - a repeated `Idempotency-Key` returns the task the first request created;
  2. `SubmissionCharge.reserve` - row-locks the subscription, brings it to the current month, and
     raises 402 when it may not submit (status) or has no credits;
  3. the endpoint creates the task and flushes it;
  4. `SubmissionCharge.charge(task)` + `remember_key` - the ledger charge and key row;
  5. the endpoint commits once. A 4xx anywhere before the commit leaves no task and no charge.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.http import PublicAPIError
from app.core.security import RequestContext
from app.models.billing import SubmissionIdempotencyKey
from app.models.platform import OrganizationEngineEntitlement, OrganizationSubscription, SubscriptionStatus
from app.models.task import Task
from app.services.billing import ledger, limits

# Wording from docs/design/subscriptions/NOVA-GeoRisk_Subscription_limit_reached.png.
NO_CREDITS = ("Your monthly analysis allowance has been reached. New analyses are paused until renewal; "
              "you can still view and download your results.")
STATUS_MESSAGES = {
    "subscription_required": "This organisation has no subscription for this system. Contact NOVA ARI.",
    "subscription_suspended": "Account suspended: contact NOVA ARI.",
    "subscription_expired": "The subscription has expired. Contact NOVA ARI to renew; results stay available.",
    "subscription_canceled": "The subscription is cancelled. Results stay available; new analyses are not.",
    "subscription_pending": "The subscription is not active yet. Contact NOVA ARI.",
}
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


def enforcement_enabled() -> bool:
    return get_settings().billing_enforcement_enabled


def subscription_for_engine(db: Session, organization_id: uuid.UUID, engine_key: str) -> OrganizationSubscription | None:
    """The subscription that grants this engine, through the entitlement's `subscription_id` link."""
    entitlement = (
        db.query(OrganizationEngineEntitlement)
        .filter(OrganizationEngineEntitlement.organization_id == organization_id,
                OrganizationEngineEntitlement.engine_key == engine_key)
        .one_or_none()
    )
    if entitlement is None or entitlement.subscription_id is None:
        return None
    return db.get(OrganizationSubscription, entitlement.subscription_id)


def block_code(subscription: OrganizationSubscription | None) -> str | None:
    """Why this subscription may not start new analyses (status only; credits are checked separately)."""
    if subscription is None:
        return "subscription_required"
    if ledger.is_current(subscription):
        return None
    if subscription.status == SubscriptionStatus.SUSPENDED:
        return "subscription_suspended"
    if subscription.status == SubscriptionStatus.CANCELED:
        return "subscription_canceled"
    if subscription.status == SubscriptionStatus.PENDING:
        return "subscription_pending"
    return "subscription_expired"


def _payment_required(code: str, message: str) -> PublicAPIError:
    return PublicAPIError(402, code, message)


@dataclass
class SubmissionCharge:
    subscription: OrganizationSubscription | None
    context: RequestContext
    engine_key: str

    @classmethod
    def reserve(cls, db: Session, context: RequestContext, engine_key: str) -> "SubmissionCharge":
        """Lock the subscription and refuse with 402 before any task exists. No-op while enforcement is off
        and for internal service calls (which have no organisation session)."""
        if not enforcement_enabled() or context.is_service:
            return cls(None, context, engine_key)
        found = subscription_for_engine(db, context.organization_id, engine_key)
        subscription = ledger.lock_subscription(db, found.id) if found is not None else None
        code = block_code(subscription)
        if code is not None:
            raise _payment_required(code, STATUS_MESSAGES[code])
        if limits.storage_blocks_submission(db, context.organization_id):
            raise _payment_required("storage_full", limits.STORAGE_FULL_MESSAGE)
        if ledger.has_unlimited_credits(db, subscription):
            return cls(None, context, engine_key)  # Internal plan: allowed, never charged
        ledger.ensure_period(db, subscription)
        if ledger.balances(db, subscription.id).total <= 0:
            raise _payment_required("credits_exhausted", NO_CREDITS)
        return cls(subscription, context, engine_key)

    def charge(self, db: Session, task: Task) -> None:
        if self.subscription is None:
            return
        if task.id is None:
            db.flush()
        try:
            ledger.charge_task(db, self.subscription, task.id, self.context.user_id, self.engine_key)
        except ledger.InsufficientCredits as exc:
            raise _payment_required("credits_exhausted", NO_CREDITS) from exc


# --- Idempotency-Key ------------------------------------------------------------------------------

def request_fingerprint(endpoint: str, payload: object) -> str:
    canonical = json.dumps({"endpoint": endpoint, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_key(key: str | None) -> str | None:
    if key is None or key == "":
        return None
    if not _KEY_PATTERN.fullmatch(key):
        raise PublicAPIError(422, "idempotency_key_invalid",
                             "Idempotency-Key must be 8-128 characters: letters, digits, '-', '_', ':' or '.'.")
    return key


def replay_or_none(
    db: Session, context: RequestContext, key: str | None, endpoint: str, fingerprint: str,
) -> Task | None:
    """Return the task created by an earlier request with this key, or None. A reused key with a different
    request body is refused (409), so a key can never be used to fetch someone else's work."""
    if key is None or context.is_service:
        return None
    row = (
        db.query(SubmissionIdempotencyKey)
        .filter(SubmissionIdempotencyKey.organization_id == context.organization_id,
                SubmissionIdempotencyKey.user_id == context.user_id,
                SubmissionIdempotencyKey.key == key)
        .one_or_none()
    )
    if row is None:
        return None
    if row.endpoint != endpoint or row.request_sha256 != fingerprint:
        raise PublicAPIError(409, "idempotency_key_reused",
                             "This Idempotency-Key was already used for a different request.")
    return db.get(Task, row.task_id)


def remember_key(db: Session, context: RequestContext, key: str | None, endpoint: str, fingerprint: str,
                 task: Task) -> None:
    if key is None or context.is_service:
        return
    if task.id is None:  # r8.1: with enforcement off nothing has flushed the new task yet (charge() only flushes with a plan)
        db.flush()
    db.add(SubmissionIdempotencyKey(organization_id=context.organization_id, user_id=context.user_id, key=key,
                                    endpoint=endpoint, request_sha256=fingerprint, task_id=task.id))
    db.flush()
