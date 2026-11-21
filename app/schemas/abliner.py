"""Customer contracts for Mobile Money payments. Never a full phone number, never a secret."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PaymentOfferResponse(BaseModel):
    purpose: Literal["top_up", "renewal"]
    available: bool
    amount: int | None
    currency: str
    credits: int | None
    covers_from: date | None
    covers_until: date | None
    # When not available: why, and what to tell the customer ("Contact NOVAREX ...").
    unavailable_code: str | None
    unavailable_message: str | None


class PaymentOffersResponse(BaseModel):
    enabled: bool
    subscription_id: uuid.UUID
    offers: list[PaymentOfferResponse]


class CreatePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: uuid.UUID
    purpose: Literal["top_up", "renewal"]
    phone: str = Field(min_length=9, max_length=20)


class PaymentIntentResponse(BaseModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    purpose: str
    amount: int
    currency: str
    credits: int | None
    covers_from: date | None
    covers_until: date | None
    phone: str  # masked, e.g. 2557•••••678
    # pending, completed, failed, expired or review. Only "completed" means anything was added.
    status: str
    message: str
    created_at: datetime
    completed_at: datetime | None
