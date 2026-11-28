"""NOVA ARI console actions that are not payments or statuses (those live in app/services/billing).

Every function takes the admin as `actor`, requires a reason and writes `platform_audit` with the
previous and current values. None commits; the endpoint commits once, so the change and its audit
row land together or not at all.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.billing import BillingPlanPrice, CreditLedgerEntry
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import (BillingPlan, EntitlementStatus, OrganizationEngineEntitlement, OrganizationSubscription,
                                 SubscriptionStatus)
from app.models.platform_admin import SecurityAlert
from app.models.sessions import UserSession
from app.services.billing import audit, bounds, catalogue, ledger
from app.services.sessions import tracking

SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$")
OVERRIDES = ("monthly_credits_override", "seat_limit_override", "storage_bytes_override", "session_limit_override",
             "refund_on_data_failure_override")
PLAN_LIMITS = ("seat_limit", "monthly_credits", "storage_bytes", "session_limit", "refund_on_data_failure")


class ActionError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _checked_overrides(overrides: dict | None) -> dict:
    """Same rules as the API schema, for every caller (security review L2)."""
    checked = {}
    for name, value in (overrides or {}).items():
        if name not in OVERRIDES:
            raise ActionError("override_invalid", f"Unknown override: {name}")
        problem = bounds.check(name, value)
        if problem:
            raise ActionError("override_invalid", problem)
        checked[name] = value
    return checked


def _plan_for(db: Session, family: str, plan_key: str) -> BillingPlan:
    plan = db.get(BillingPlan, plan_key)
    if plan is None or plan.family != family or plan.status != "active":
        raise ActionError("plan_invalid", f"{plan_key} is not an active {family} plan.")
    return plan


def _subscription_view(subscription: OrganizationSubscription) -> dict:
    view = {"family": subscription.family, "plan_key": subscription.plan_key, "status": subscription.status.value,
            "starts_at": subscription.starts_at.isoformat() if subscription.starts_at else None,
            "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None}
    view.update({name: getattr(subscription, name) for name in OVERRIDES})
    return view


def _link_entitlements(db: Session, subscription: OrganizationSubscription, actor: audit.Actor) -> list[str]:
    """Each engine of the family gets an active entitlement linked to the subscription (viewing and
    downloads are gated by entitlements; new analyses by the subscription)."""
    linked = []
    for engine_key in catalogue.family_engines(subscription.family):
        entitlement = (db.query(OrganizationEngineEntitlement)
                       .filter(OrganizationEngineEntitlement.organization_id == subscription.organization_id,
                               OrganizationEngineEntitlement.engine_key == engine_key).one_or_none())
        if entitlement is None:
            from app.models.platform import Engine
            if db.get(Engine, engine_key) is None:
                continue
            entitlement = OrganizationEngineEntitlement(
                organization_id=subscription.organization_id, engine_key=engine_key, status=EntitlementStatus.ACTIVE,
                source="nova_ari_console", starts_at=subscription.starts_at, granted_by_user_id=actor.user_id)
            db.add(entitlement)
        entitlement.subscription_id = subscription.id
        linked.append(engine_key)
    db.flush()
    return linked


def add_subscription(
    db: Session, organization_id: uuid.UUID, *, family: str, plan_key: str, reason: str, actor: audit.Actor,
    starts_at: datetime | None = None, ends_at: datetime | None = None, overrides: dict | None = None,
) -> OrganizationSubscription:
    reason = audit.require_reason(reason)
    if db.get(Organization, organization_id) is None:
        raise ActionError("organization_not_found", "Organisation not found.", 404)
    _plan_for(db, family, plan_key)
    if db.query(OrganizationSubscription).filter(OrganizationSubscription.organization_id == organization_id,
                                                 OrganizationSubscription.family == family).first():
        raise ActionError("subscription_exists", "This customer already has a subscription for this system.", 409)
    now = datetime.now(timezone.utc)
    if ends_at is not None and ends_at <= (starts_at or now):
        raise ActionError("dates_invalid", "The end date must be after the start date.")
    subscription = OrganizationSubscription(
        organization_id=organization_id, family=family, plan_key=plan_key, status=SubscriptionStatus.ACTIVE,
        starts_at=starts_at or now, ends_at=ends_at, status_changed_at=now, source="nova_ari_console")
    for name, value in _checked_overrides(overrides).items():
        setattr(subscription, name, value)
    db.add(subscription)
    db.flush()
    engines = _link_entitlements(db, subscription, actor)
    audit.record(db, actor, "subscription.create", reason=reason, organization_id=organization_id,
                 target_type="subscription", target_id=subscription.id,
                 current={**_subscription_view(subscription), "engines": engines})
    return subscription


def add_customer(
    db: Session, *, name: str, slug: str, family: str, plan_key: str, reason: str, actor: audit.Actor,
    starts_at: datetime | None = None, ends_at: datetime | None = None, overrides: dict | None = None,
    owner_issuer: str | None = None, owner_subject: str | None = None, owner_email: str | None = None,
    owner_name: str | None = None,
) -> tuple[Organization, OrganizationSubscription, User | None]:
    """Organisation + first subscription (+ engine access) + optionally the first owner.

    The owner is provisioned like the existing administration route: by the exact configured OIDC
    issuer and the provider-verified subject (the production membership policy is "strict", where
    invitations do not grant access). Without an owner, add one later the usual way."""
    reason = audit.require_reason(reason)
    name = (name or "").strip()
    slug = (slug or "").strip().lower()
    if not 2 <= len(name) <= 255:
        raise ActionError("name_invalid", "The organisation name must be 2 to 255 characters.")
    if not SLUG.fullmatch(slug):
        raise ActionError("slug_invalid", "The short name must be 3 to 64 lowercase letters, digits or dashes.")
    if db.query(Organization).filter(Organization.slug == slug).first():
        raise ActionError("slug_taken", "Another organisation already uses this short name.", 409)
    owner = None
    if owner_subject or owner_issuer:
        issuer = get_settings().oidc_issuer_url
        if not issuer or owner_issuer != issuer or not (owner_subject or "").strip():
            raise ActionError("owner_identity_invalid",
                              "Use the exact configured identity-provider issuer and the person's verified subject.")
    organization = Organization(name=name, slug=slug)
    db.add(organization)
    db.flush()
    if owner_subject:
        owner = db.query(User).filter(User.issuer == owner_issuer, User.subject == owner_subject.strip()).one_or_none()
        if owner is None:
            owner = User(issuer=owner_issuer, subject=owner_subject.strip(), email=(owner_email or None),
                         display_name=(owner_name or None), is_active=True)
            db.add(owner)
            db.flush()
        db.add(OrganizationMembership(organization_id=organization.id, user_id=owner.id, role=MembershipRole.OWNER))
        db.flush()
    audit.record(db, actor, "organization.create", reason=reason, organization_id=organization.id,
                 target_type="organization", target_id=organization.id,
                 current={"name": name, "slug": slug, "owner_user_id": str(owner.id) if owner else None})
    subscription = add_subscription(db, organization.id, family=family, plan_key=plan_key, reason=reason, actor=actor,
                                    starts_at=starts_at, ends_at=ends_at, overrides=overrides)
    return organization, subscription, owner


def change_plan(
    db: Session, subscription_id: uuid.UUID, *, plan_key: str | None, reason: str, actor: audit.Actor,
    overrides: dict | None = None,
) -> OrganizationSubscription:
    """Change the plan (same system) and/or the per-contract overrides. The new monthly allowance applies
    from the next billing month; on an upgrade, this month's difference is added now as an adjustment."""
    reason = audit.require_reason(reason)
    subscription = ledger.lock_subscription(db, subscription_id)
    previous = _subscription_view(subscription)
    if plan_key is not None and plan_key != subscription.plan_key:
        _plan_for(db, subscription.family, plan_key)
        subscription.plan_key = plan_key
    for name, value in _checked_overrides(overrides).items():
        setattr(subscription, name, value)
    current = _subscription_view(subscription)
    if current == previous:
        raise ActionError("no_change", "Nothing would change.", 409)
    db.flush()
    db.expire(subscription, ["plan"])
    record = audit.record(db, actor, "subscription.change_plan", reason=reason,
                          organization_id=subscription.organization_id, target_type="subscription",
                          target_id=subscription.id, previous=previous, current=current)
    new_credits = ledger.effective_monthly_credits(db, subscription)
    period = ledger.period_of()
    grant = ledger.entry_by_key(db, ledger.grant_key(subscription.id, period))
    if grant is not None and not ledger.has_unlimited_credits(db, subscription):
        # Security review L3: top up only above the highest allowance already given this month (the grant plus
        # earlier plan-change top-ups), so switching plans up, down and up again never adds credits twice.
        already = grant.amount + _plan_change_top_ups(db, subscription.id, period)
        top_up = new_credits - already
        if top_up > 0:
            ledger.append_entry(db, subscription, kind="adjustment", bucket="monthly", amount=top_up,
                                key=f"planchange:{record.id}", actor_user_id=actor.user_id,
                                reason=f"Plan change this month: allowance {already} -> {new_credits}. {reason}",
                                metadata={"audit_id": str(record.id), "allowance_before": already,
                                          "allowance_after": new_credits})
    return subscription


def _plan_change_top_ups(db: Session, subscription_id: uuid.UUID, period: str) -> int:
    return int(db.query(func.coalesce(func.sum(CreditLedgerEntry.amount), 0))
               .filter(CreditLedgerEntry.subscription_id == subscription_id, CreditLedgerEntry.period == period,
                       CreditLedgerEntry.kind == "adjustment",
                       CreditLedgerEntry.idempotency_key.like("planchange:%")).scalar() or 0)


def end_sessions(
    db: Session, tracker: tracking.SessionTracker, *, organization_id: uuid.UUID, user_id: uuid.UUID | None,
    reason: str, actor: audit.Actor,
) -> int:
    """End every active session of one user, or of every member of the organisation."""
    reason = audit.require_reason(reason)
    now = datetime.now(timezone.utc)
    query = db.query(UserSession).filter(UserSession.organization_id == organization_id,
                                         UserSession.ended_at.is_(None), UserSession.expires_at > now)
    if user_id is not None:
        query = query.filter(UserSession.user_id == user_id)
    rows = query.all()
    for row in rows:
        tracker.end(db, row, reason="ended_by_admin", now=now)
    audit.record(db, actor, "sessions.end", reason=reason, organization_id=organization_id,
                 target_type="user" if user_id else "organization", target_id=user_id or organization_id,
                 current={"ended": len(rows), "session_ids": [str(row.id) for row in rows]})
    return len(rows)


def acknowledge_alert(db: Session, alert_id: uuid.UUID, *, reason: str, actor: audit.Actor) -> SecurityAlert:
    reason = audit.require_reason(reason)
    alert = db.get(SecurityAlert, alert_id)
    if alert is None:
        raise ActionError("alert_not_found", "Alert not found.", 404)
    if alert.acknowledged_at is not None:
        raise ActionError("alert_closed", "This alert is already reviewed.", 409)
    alert.acknowledged_at, alert.acknowledged_by_user_id, alert.acknowledge_reason = (
        datetime.now(timezone.utc), actor.user_id, reason)
    db.flush()
    audit.record(db, actor, "security_alert.acknowledge", reason=reason, organization_id=alert.organization_id,
                 target_type="security_alert", target_id=alert.id, previous={"open": True}, current={"open": False})
    return alert


def new_price_version(
    db: Session, plan_key: str, *, monthly_price: int | None, top_up_credit_price: int | None, reason: str,
    actor: audit.Actor, effective_from: datetime | None = None, source: str = "nova_ari_console",
) -> BillingPlanPrice:
    """Prices are versioned: a change is a new row; earlier versions stay (append-only)."""
    reason = audit.require_reason(reason)
    plan = db.get(BillingPlan, plan_key)
    if plan is None or plan.is_internal:
        raise ActionError("plan_invalid", "Plan not found, or not sold.", 404)
    for value in (monthly_price, top_up_credit_price):
        if value is not None and (value < 0 or value > 10_000_000_000):
            raise ActionError("price_invalid", "Prices are whole TZS between 0 and 10,000,000,000.")
    if top_up_credit_price == 0:
        raise ActionError("price_invalid", "A top-up credit price must be positive, or empty for no top-ups.")
    current = catalogue.current_price(db, plan_key)
    version = (db.query(BillingPlanPrice.version).filter(BillingPlanPrice.plan_key == plan_key)
               .order_by(BillingPlanPrice.version.desc()).limit(1).scalar() or 0) + 1
    row = BillingPlanPrice(plan_key=plan_key, version=version, currency=catalogue.load_catalogue()["currency"],
                           monthly_price=monthly_price, top_up_credit_price=top_up_credit_price,
                           effective_from=effective_from or datetime.now(timezone.utc), source=source,
                           reason=reason, created_by_user_id=actor.user_id)
    db.add(row)
    db.flush()
    audit.record(db, actor, "plan.price", reason=reason, organization_id=None, target_type="plan", target_id=plan_key,
                 previous={"version": current.version, "monthly_price": current.monthly_price,
                           "top_up_credit_price": current.top_up_credit_price} if current else None,
                 current={"version": version, "monthly_price": monthly_price,
                          "top_up_credit_price": top_up_credit_price})
    return row


def update_plan_limits(db: Session, plan_key: str, *, changes: dict, reason: str, actor: audit.Actor) -> BillingPlan:
    """Edit a plan's limits for every subscription on it (overrides still win). Audited before/after."""
    reason = audit.require_reason(reason)
    plan = db.query(BillingPlan).filter(BillingPlan.key == plan_key).with_for_update().one_or_none()
    if plan is None:
        raise ActionError("plan_invalid", "Plan not found.", 404)
    previous = {name: getattr(plan, name) for name in PLAN_LIMITS}
    for name, value in changes.items():
        if name not in PLAN_LIMITS:
            raise ActionError("limit_invalid", f"Unknown limit: {name}")
        if name == "refund_on_data_failure" and value is None:
            raise ActionError("limit_invalid", "refund_on_data_failure must be true or false.")
        problem = bounds.check(name, value)
        if problem:
            raise ActionError("limit_invalid", problem)
        setattr(plan, name, value)
    current = {name: getattr(plan, name) for name in PLAN_LIMITS}
    if current == previous:
        raise ActionError("no_change", "Nothing would change.", 409)
    db.flush()
    audit.record(db, actor, "plan.limits", reason=reason, organization_id=None, target_type="plan",
                 target_id=plan_key, previous=previous, current=current)
    return plan
