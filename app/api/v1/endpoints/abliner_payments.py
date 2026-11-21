"""Mobile Money payments on "My subscription" (docs/ABLINER_PAYMENTS_PLAN.md §1). Owners and admins only,
organisation-scoped. Pending is never paid: credits or a plan period are added only by settlement."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.v1.endpoints.billing import _require_billing_role, _require_member
from app.core.config import get_settings
from app.core.http import PublicAPIError
from app.core.security import RequestContext, get_request_context, verify_internal_secret
from app.db.session import get_db
from app.models.abliner import PaymentIntent
from app.models.platform import OrganizationSubscription
from app.schemas.abliner import CreatePaymentRequest, PaymentIntentResponse, PaymentOfferResponse, PaymentOffersResponse
from app.services.abliner import client as abliner_client
from app.services.abliner import intents
from app.services.billing.submission import validate_key

router = APIRouter(prefix="/billing/abliner", tags=["Mobile Money"], dependencies=[Depends(verify_internal_secret)])


def get_abliner_client() -> abliner_client.AblinerClient:
    return abliner_client.get_client()


def _view(intent: PaymentIntent) -> PaymentIntentResponse:
    return PaymentIntentResponse(
        id=intent.id, subscription_id=intent.subscription_id, purpose=intent.purpose, amount=intent.amount,
        currency=intent.currency, credits=intent.credits, covers_from=intent.covers_from, covers_until=intent.covers_until,
        phone=intent.phone_masked, status=intents.customer_status(intent), message=intents.customer_message(intent),
        created_at=intent.created_at, completed_at=intent.completed_at)


@router.get("/offers", response_model=PaymentOffersResponse)
def payment_offers(subscription_id: uuid.UUID, db: Session = Depends(get_db),
                   context: RequestContext = Depends(get_request_context)) -> PaymentOffersResponse:
    """What Mobile Money can pay for this subscription (list prices are not secret; any member may read)."""
    _require_member(db, context)
    subscription = db.get(OrganizationSubscription, subscription_id)
    if subscription is None or subscription.organization_id != context.organization_id or subscription.family is None:
        raise PublicAPIError(404, "subscription_not_found", "Subscription not found.")
    offers = [intents.offer(db, subscription, purpose) for purpose in ("top_up", "renewal")]
    return PaymentOffersResponse(enabled=get_settings().abliner_payments_enabled, subscription_id=subscription.id,
                                 offers=[PaymentOfferResponse(**offer.__dict__) for offer in offers])


@router.post("/payments", response_model=PaymentIntentResponse, status_code=201)
def create_payment(body: CreatePaymentRequest, db: Session = Depends(get_db),
                   context: RequestContext = Depends(get_request_context),
                   client: abliner_client.AblinerClient = Depends(get_abliner_client),
                   idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> PaymentIntentResponse:
    _require_billing_role(db, context)
    key = validate_key(idempotency_key)
    if key is None:
        raise PublicAPIError(422, "idempotency_key_required", "Send an Idempotency-Key header (8-128 characters).")
    intent, _ = intents.create(db, organization_id=context.organization_id, user_id=context.user_id,
                               subscription_id=body.subscription_id, purpose=body.purpose, phone_number=body.phone,
                               request_key=key, client=client)
    return _view(intent)


@router.get("/payments", response_model=list[PaymentIntentResponse])
def list_payments(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db),
                  context: RequestContext = Depends(get_request_context)) -> list[PaymentIntentResponse]:
    _require_billing_role(db, context)
    rows = (db.query(PaymentIntent).filter(PaymentIntent.organization_id == context.organization_id)
            .order_by(PaymentIntent.created_at.desc()).limit(limit).all())
    return [_view(row) for row in rows]


@router.get("/payments/{intent_id}", response_model=PaymentIntentResponse)
def get_payment(intent_id: uuid.UUID, db: Session = Depends(get_db),
                context: RequestContext = Depends(get_request_context)) -> PaymentIntentResponse:
    _require_billing_role(db, context)
    intent = db.get(PaymentIntent, intent_id)
    if intent is None or intent.organization_id != context.organization_id:
        raise PublicAPIError(404, "payment_not_found", "Payment not found.")
    return _view(intent)
