"""Organisation-level plan limits: seats and storage (plan sections 3 and 8).

An organisation can hold one subscription per plan family. Seats are people, so the seat limit is the
largest of its subscriptions' limits; storage is bought per system, so the storage limit is their sum.
A subscription without a value for a limit (a custom contract with no override, or the Internal plan)
means "no limit". An organisation with no subscription has no limits here; the submission check refuses
it separately (`subscription_required`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import BigInteger, cast, func, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.http import PublicAPIError
from app.models.identity import Organization, OrganizationMembership, User
from app.models.management import ManagedDataset
from app.models.platform import OrganizationSubscription
from app.services.billing import ledger

SEAT_LIMIT_MESSAGE = ("This organisation has used all the seats in its plan. "
                      "Remove a member or contact NOVA ARI to add seats.")
STORAGE_FULL_MESSAGE = ("This organisation's storage is full. New analyses are paused until space is freed or "
                        "added; you can still view and download your results. Free up space or request more "
                        "storage on My subscription.")


@dataclass(frozen=True)
class Allowance:
    used: int
    limit: int | None  # None = no limit

    @property
    def level(self) -> int | None:
        if self.limit is None:
            return None
        if self.used >= self.limit:
            return 100
        percent = 100.0 * self.used / self.limit if self.limit > 0 else 100.0
        for threshold in sorted(get_settings().billing_storage_warning_percents, reverse=True):
            if percent >= threshold:
                return threshold
        return None

    @property
    def full(self) -> bool:
        return self.limit is not None and self.used >= self.limit


def subscriptions(db: Session, organization_id: uuid.UUID) -> list[OrganizationSubscription]:
    return (
        db.query(OrganizationSubscription)
        .filter(OrganizationSubscription.organization_id == organization_id,
                OrganizationSubscription.family.isnot(None))
        .order_by(OrganizationSubscription.family)
        .all()
    )


def _combine(values: list[int | None], how) -> int | None:
    if not values or any(value is None for value in values):
        return None
    return how(values)


# --- seats ----------------------------------------------------------------------------------------

def seats_used(db: Session, organization_id: uuid.UUID) -> int:
    return (
        db.query(OrganizationMembership)
        .join(User, User.id == OrganizationMembership.user_id)
        .filter(OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.status == "active", User.is_active.is_(True))
        .count()
    )


def seat_limit(db: Session, organization_id: uuid.UUID) -> int | None:
    limits = [ledger.effective_limits(db, item)["seat_limit"] for item in subscriptions(db, organization_id)]
    return _combine(limits, max)


def seats(db: Session, organization_id: uuid.UUID) -> Allowance:
    return Allowance(used=seats_used(db, organization_id), limit=seat_limit(db, organization_id))


def ensure_seat_available(db: Session, organization_id: uuid.UUID) -> None:
    """Refuse a new active membership when the organisation's seats are all used. Takes the organisation
    row lock (the same lock membership changes already take), so two parallel additions cannot both
    take the last seat. No-op while enforcement is off."""
    if not get_settings().billing_enforcement_enabled:
        return
    db.query(Organization.id).filter(Organization.id == organization_id).with_for_update().one()
    if seats(db, organization_id).full:
        raise SeatLimitReached()


class SeatLimitReached(PublicAPIError):
    def __init__(self) -> None:
        super().__init__(409, "seat_limit_reached", SEAT_LIMIT_MESSAGE)


# --- storage --------------------------------------------------------------------------------------

# Sizes are recorded in each output_files entry when a result is published (`file_size_bytes`).
_RESULT_BYTES = text("""
    SELECT coalesce(sum((entry.value ->> 'file_size_bytes')::bigint), 0)
    FROM results r
    JOIN projects p ON p.id = r.project_id
    CROSS JOIN LATERAL jsonb_each(
        CASE WHEN jsonb_typeof(r.output_files) = 'object' THEN r.output_files ELSE '{}'::jsonb END) AS entry
    WHERE p.organization_id = :organization_id
      AND jsonb_typeof(entry.value) = 'object'
      AND (entry.value ->> 'file_size_bytes') ~ '^[0-9]{1,18}$'
""")


def storage_used(db: Session, organization_id: uuid.UUID) -> int:
    """Bytes of the organisation's result files (recorded per file at publication) plus its uploaded
    external datasets."""
    results = db.execute(_RESULT_BYTES, {"organization_id": organization_id}).scalar()
    datasets = (
        db.query(func.coalesce(func.sum(cast(ManagedDataset.size_bytes, BigInteger)), 0))
        .filter(ManagedDataset.organization_id == organization_id)
        .scalar()
    )
    return int(results or 0) + int(datasets or 0)


def storage_limit(db: Session, organization_id: uuid.UUID) -> int | None:
    limits = [ledger.effective_limits(db, item)["storage_bytes"] for item in subscriptions(db, organization_id)]
    return _combine(limits, sum)


def storage(db: Session, organization_id: uuid.UUID) -> Allowance:
    return Allowance(used=storage_used(db, organization_id), limit=storage_limit(db, organization_id))


def storage_blocks_submission(db: Session, organization_id: uuid.UUID) -> bool:
    """Q5 (decided): at 100% new analyses are blocked (setting, on by default). Never viewing or downloads."""
    return get_settings().billing_storage_block_at_limit and storage(db, organization_id).full


# --- sessions -------------------------------------------------------------------------------------

def session_limit(db: Session, organization_id: uuid.UUID) -> int | None:
    """Active browser sessions allowed per user (Researcher 1, others 3, Q8). Per person like seats, so
    the largest of the organisation's subscriptions applies. None = no limit, including while
    enforcement is off and for an organisation without a subscription."""
    if not get_settings().billing_enforcement_enabled:
        return None
    values = [ledger.effective_limits(db, item)["session_limit"] for item in subscriptions(db, organization_id)]
    return _combine(values, max)
