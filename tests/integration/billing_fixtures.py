"""A paid, Active subscription for test tenants that are not about billing (security review, tests).

The owner rule after r8.1 is that the whole suite runs with billing enforcement both OFF and ON. With enforcement ON
every new analysis needs an Active subscription with credits, as in production after Phase B. Engine tests
(FRRIS, source-bound modules) therefore give their tenant one, on a real sold plan, linked through the engine
entitlement exactly as the console does. Charge-on-submit and refunds then run for real in those tests.

Enterprise (250 credits a month) is used so that no engine test runs out of credits.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.platform import OrganizationEngineEntitlement, OrganizationSubscription, SubscriptionStatus
from app.services.billing import catalogue

PLAN_KEY = "frris_wrris.enterprise"


def subscribe(db: Session, organization_id: uuid.UUID, engine_key: str = "firris",
              plan_key: str = PLAN_KEY) -> OrganizationSubscription:
    """Active subscription on `plan_key`, linked to the organisation's existing entitlement for `engine_key`."""
    catalogue.seed_catalogue(db)
    subscription = OrganizationSubscription(
        organization_id=organization_id, plan_key=plan_key, family="frris_wrris", status=SubscriptionStatus.ACTIVE,
        starts_at=datetime.now(timezone.utc) - timedelta(days=1), source="engine-test")
    db.add(subscription)
    db.flush()
    entitlement = (db.query(OrganizationEngineEntitlement)
                   .filter(OrganizationEngineEntitlement.organization_id == organization_id,
                           OrganizationEngineEntitlement.engine_key == engine_key).one())
    entitlement.subscription_id = subscription.id
    db.flush()
    return subscription
