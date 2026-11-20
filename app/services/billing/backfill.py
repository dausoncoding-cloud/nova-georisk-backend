"""Give every existing organisation a subscription before enforcement is switched on (release record,
turn-on checklist). Dry run by default: `plan()` only reads; `apply()` writes everything in one
transaction, or nothing if any organisation still needs a plan.

For each organisation and each plan family whose engines it has an entitlement for:
- `ok`      a family subscription exists and every entitlement of that family links to it;
- `link`    a family subscription exists; link the unlinked entitlements to it;
- `adopt`   an entitlement already links to an older subscription with no family: give it the family
            and plan, and link the family's other entitlements;
- `create`  create an Active subscription with the chosen plan and link the entitlements;
- `needs_plan`  no plan was given for this family (apply refuses until there is one).
Organisations with no entitlement in a family are reported once as `no_engine_access` and left alone.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.identity import Organization
from app.models.platform import (BillingPlan, EntitlementStatus, OrganizationEngineEntitlement, OrganizationSubscription,
                                 SubscriptionStatus)
from app.services.billing import audit, catalogue

# The subscription mirrors the entitlement's current state, so the backfill never opens or closes access.
_STATUS_FROM_ENTITLEMENT = {
    EntitlementStatus.ACTIVE: SubscriptionStatus.ACTIVE, EntitlementStatus.TRIAL: SubscriptionStatus.TRIAL,
    EntitlementStatus.SUSPENDED: SubscriptionStatus.SUSPENDED, EntitlementStatus.EXPIRED: SubscriptionStatus.EXPIRED,
    EntitlementStatus.CANCELED: SubscriptionStatus.CANCELED, EntitlementStatus.PENDING: SubscriptionStatus.PENDING,
}


class BackfillError(ValueError):
    pass


@dataclass
class Step:
    action: str
    organization_id: uuid.UUID
    organization: str
    family: str | None = None
    plan_key: str | None = None
    subscription_id: uuid.UUID | None = None
    status: str | None = None
    engines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"action": self.action, "organization": self.organization, "organization_id": str(self.organization_id),
                "family": self.family, "plan_key": self.plan_key,
                "subscription_id": str(self.subscription_id) if self.subscription_id else None,
                "status": self.status, "engines": self.engines}


def _resolve_org(db: Session, value: str) -> Organization:
    try:
        found = db.get(Organization, uuid.UUID(value))
    except ValueError:
        found = db.query(Organization).filter(Organization.slug == value).one_or_none()
    if found is None:
        raise BackfillError(f"Organisation not found: {value}")
    return found


def _check_plan(db: Session, family: str, plan_key: str) -> None:
    plan = db.get(BillingPlan, plan_key)
    if plan is None or plan.family != family:
        raise BackfillError(f"Plan {plan_key} is not a {family} plan.")


def plan(db: Session, *, default_plans: dict[str, str], internal_orgs: list[str],
         org_plans: dict[str, str] | None = None) -> list[Step]:
    """Read-only. `default_plans` maps family -> plan key; `internal_orgs` (slug or ID) get the family's
    Internal plan; `org_plans` maps "<org slug or ID>:<family>" -> plan key for individual exceptions."""
    families = catalogue.load_catalogue()["families"]
    for family, plan_key in default_plans.items():
        if family not in families:
            raise BackfillError(f"Unknown plan family: {family}")
        _check_plan(db, family, plan_key)
    internal_ids = {_resolve_org(db, value).id for value in internal_orgs}
    exceptions: dict[tuple[uuid.UUID, str], str] = {}
    for target, plan_key in (org_plans or {}).items():
        org_value, _, family = target.rpartition(":")
        if family not in families:
            raise BackfillError(f"Unknown plan family in {target}")
        _check_plan(db, family, plan_key)
        exceptions[(_resolve_org(db, org_value).id, family)] = plan_key

    steps: list[Step] = []
    for organization in db.query(Organization).order_by(Organization.slug):
        entitlements = (
            db.query(OrganizationEngineEntitlement)
            .filter(OrganizationEngineEntitlement.organization_id == organization.id)
            .order_by(OrganizationEngineEntitlement.engine_key)
            .all()
        )
        touched = False
        for family, spec in families.items():
            own = [item for item in entitlements if item.engine_key in spec["engines"]]
            if not own:
                continue
            touched = True
            engines = [item.engine_key for item in own]
            chosen = (catalogue.internal_plan_key(family) if organization.id in internal_ids
                      else exceptions.get((organization.id, family)) or default_plans.get(family))
            existing = (db.query(OrganizationSubscription)
                        .filter(OrganizationSubscription.organization_id == organization.id,
                                OrganizationSubscription.family == family).one_or_none())
            base = dict(organization_id=organization.id, organization=organization.slug, family=family, engines=engines)
            if existing is not None:
                unlinked = [item.engine_key for item in own if item.subscription_id != existing.id]
                steps.append(Step("link" if unlinked else "ok", plan_key=existing.plan_key,
                                  subscription_id=existing.id, status=existing.status.value, **base))
                continue
            legacy = next((item.subscription for item in own
                           if item.subscription is not None and item.subscription.family is None), None)
            if chosen is None:
                steps.append(Step("needs_plan", subscription_id=legacy.id if legacy else None, **base))
                continue
            if legacy is not None:
                steps.append(Step("adopt", plan_key=chosen, subscription_id=legacy.id, status=legacy.status.value, **base))
                continue
            status = _STATUS_FROM_ENTITLEMENT[own[0].status]
            steps.append(Step("create", plan_key=chosen, status=status.value, **base))
        if not touched:
            steps.append(Step("no_engine_access", organization_id=organization.id, organization=organization.slug))
    return steps


def apply(db: Session, steps: list[Step], *, reason: str, actor: audit.Actor) -> list[Step]:
    """Write the planned steps (the caller commits). Refuses the whole run if any step needs a plan."""
    reason = audit.require_reason(reason)
    missing = [f"{step.organization}:{step.family}" for step in steps if step.action == "needs_plan"]
    if missing:
        raise BackfillError("No plan given for: " + ", ".join(missing) + ". Use --plan or --org-plan.")
    now = datetime.now(timezone.utc)
    for step in steps:
        if step.action in {"ok", "no_engine_access"}:
            continue
        family_engines = set(catalogue.family_engines(step.family))
        entitlements = [item for item in db.query(OrganizationEngineEntitlement).filter(
            OrganizationEngineEntitlement.organization_id == step.organization_id) if item.engine_key in family_engines]
        if step.action == "create":
            subscription = OrganizationSubscription(
                organization_id=step.organization_id, family=step.family, plan_key=step.plan_key,
                status=SubscriptionStatus(step.status), starts_at=now, status_changed_at=now, source="backfill",
                trial_ends_at=next((item.trial_ends_at for item in entitlements if item.trial_ends_at), None))
            db.add(subscription)
            db.flush()
            previous = None
        else:
            subscription = db.get(OrganizationSubscription, step.subscription_id)
            previous = {"family": subscription.family, "plan_key": subscription.plan_key}
            if step.action == "adopt":
                subscription.family, subscription.plan_key = step.family, step.plan_key
        links = []
        for item in entitlements:
            if item.subscription_id != subscription.id:
                links.append({"engine": item.engine_key,
                              "from": str(item.subscription_id) if item.subscription_id else None})
                item.subscription_id = subscription.id
        db.flush()
        step.subscription_id = subscription.id
        audit.record(db, actor, f"subscription.backfill_{step.action}", reason=reason,
                     organization_id=step.organization_id, target_type="subscription", target_id=subscription.id,
                     previous=previous,
                     current={"family": step.family, "plan_key": subscription.plan_key,
                              "status": subscription.status.value, "entitlement_links": links})
    return steps
