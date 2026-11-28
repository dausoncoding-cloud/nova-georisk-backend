"""A test organisation in production, only for the owner's TZS 500 Abliner live test (fix round r5, item 6).

    python -m app.services.billing.cli create-test-organization --reason "..." [--slug nova-payments-test] [--apply]

What it creates (dry run unless --apply; safe to repeat):
- an organisation (default slug `nova-payments-test`, name "NOVA ARI payment test (not a customer)") with NO members,
  NO engine entitlement and NO projects: nobody can sign in to it or run analyses in it;
- one Active subscription on the Internal plan `frris_wrris.internal` (not paid for, no credit or seat limit),
  source `test-organization`, metadata `{"test_organization": true, "purpose": "abliner-live-test"}`.
It prints the subscription ID that `python -m app.services.abliner.cli test-payment --subscription-id <id>` takes.
Both writes are audited (`organization.test_created`, `subscription.test_created`, actor "operator command:
create-test-organization") with the reason. A repeat returns the same IDs. Any existing organisation with that slug
that this command did not create is refused, so a customer organisation is never touched.

Removing it later is a NOVA ARI console action (cancel the subscription); its test payment and audit rows stay.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.identity import Organization, OrganizationMembership
from app.models.platform import OrganizationEngineEntitlement, OrganizationSubscription, SubscriptionStatus
from app.services.billing import audit, catalogue

DEFAULT_SLUG = "nova-payments-test"
NAME = "NOVA ARI payment test (not a customer)"
FAMILY = "frris_wrris"
SOURCE = "test-organization"
MARKER = {"test_organization": True, "purpose": "abliner-live-test"}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")


class TestOrganizationError(ValueError):
    pass


@dataclass
class Report:
    action: str  # "create" (dry run), "created", "exists"
    slug: str
    organization_id: str | None = None
    subscription_id: str | None = None
    plan_key: str = catalogue.internal_plan_key(FAMILY)

    def as_dict(self) -> dict:
        return {"action": self.action, "slug": self.slug, "organization_id": self.organization_id,
                "subscription_id": self.subscription_id, "plan_key": self.plan_key, "members": 0, "engines": [],
                "next": ("python -m app.services.abliner.cli test-payment --subscription-id "
                         f"{self.subscription_id or '<subscription_id>'} --admin-email <NOVA ARI admin e-mail> "
                         "--operator \"<name>\"")}


def _test_subscription(db: Session, organization: Organization) -> OrganizationSubscription | None:
    rows = db.query(OrganizationSubscription).filter(OrganizationSubscription.organization_id == organization.id).all()
    if len(rows) == 1 and rows[0].source == SOURCE and (rows[0].metadata_json or {}).get("test_organization") is True:
        return rows[0]
    return None


def ensure(db: Session, *, slug: str = DEFAULT_SLUG, reason: str | None, apply: bool) -> Report:
    """Dry run unless `apply`; the caller commits."""
    slug = (slug or "").strip().lower()
    if not _SLUG.fullmatch(slug):
        raise TestOrganizationError(f"Invalid slug: {slug!r} (lowercase letters, digits and hyphens, 3-63 characters).")
    plan_key = catalogue.internal_plan_key(FAMILY)
    catalogue.seed_catalogue(db)  # idempotent; the Internal plan exists after the migrations anyway
    existing = db.query(Organization).filter(Organization.slug == slug).one_or_none()
    if existing is not None:
        subscription = _test_subscription(db, existing)
        has_people = db.query(OrganizationMembership.user_id).filter(
            OrganizationMembership.organization_id == existing.id).first() is not None
        has_engines = db.query(OrganizationEngineEntitlement.id).filter(
            OrganizationEngineEntitlement.organization_id == existing.id).first() is not None
        if subscription is None or has_people or has_engines:
            raise TestOrganizationError(f"Organisation {slug!r} exists and is not this command's test organisation; "
                                        "it is left untouched. Choose another --slug.")
        return Report("exists", slug, str(existing.id), str(subscription.id), subscription.plan_key)
    if not apply:
        return Report("create", slug)
    actor = audit.Actor.command("create-test-organization")
    reason = audit.require_reason(reason)
    now = datetime.now(timezone.utc)
    organization = Organization(name=NAME, slug=slug)
    db.add(organization)
    db.flush()
    subscription = OrganizationSubscription(
        organization_id=organization.id, family=FAMILY, plan_key=plan_key, status=SubscriptionStatus.ACTIVE,
        starts_at=now, status_changed_at=now, source=SOURCE, metadata_json=dict(MARKER))
    db.add(subscription)
    db.flush()
    audit.record(db, actor, "organization.test_created", reason=reason, organization_id=organization.id,
                 target_type="organization", target_id=organization.id, previous=None,
                 current={"slug": slug, "name": NAME, "members": 0, "engines": []})
    audit.record(db, actor, "subscription.test_created", reason=reason, organization_id=organization.id,
                 target_type="subscription", target_id=subscription.id, previous=None,
                 current={"family": FAMILY, "plan_key": plan_key, "status": subscription.status.value, **MARKER})
    return Report("created", slug, str(organization.id), str(subscription.id), plan_key)
