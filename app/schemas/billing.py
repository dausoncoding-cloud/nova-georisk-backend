"""Customer-facing subscription and credit contracts."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CreditSummary(BaseModel):
    period: str
    granted: int
    top_ups: int
    used: int
    remaining: int
    available: int
    used_percent: float
    # None, 75, 90 or 100 (no credits left).
    level: int | None
    # Internal plan: never charged; `remaining` and `level` are not meaningful.
    unlimited: bool = False


class Allowance(BaseModel):
    used: int
    # None = no limit.
    limit: int | None
    # None, 75, 90 or 100.
    level: int | None


class PlanLimits(BaseModel):
    seat_limit: int | None
    monthly_credits: int | None
    storage_bytes: int | None
    session_limit: int | None


class TopUpOffer(BaseModel):
    credits: int
    price: int
    currency: str


class PlanOption(BaseModel):
    key: str
    family: str
    name: str
    is_custom: bool
    currency: str
    # None for a custom (contract) plan.
    monthly_price: int | None
    limits: PlanLimits


class PlanCatalogueResponse(BaseModel):
    family: str
    plans: list[PlanOption]


class SubscriptionSummary(BaseModel):
    id: uuid.UUID
    family: str
    plan_key: str | None
    plan_name: str | None
    is_internal: bool = False
    status: str
    status_label: str
    starts_at: datetime | None
    ends_at: datetime | None
    engines: list[str]
    currency: str
    monthly_price: int | None
    # Plan limits with this subscription's per-contract overrides applied.
    limits: PlanLimits
    seats_used: int
    # Next billing-month start, or the subscription end if that comes first.
    renews_on: datetime | None
    warning_levels: list[int]
    # None while top-ups are unavailable for this plan (for example MEGIS until Q2 is decided).
    top_up: TopUpOffer | None
    credits: CreditSummary
    can_submit: bool
    block_code: str | None
    block_message: str | None


class BillingSummaryResponse(BaseModel):
    enforcement_enabled: bool
    subscriptions: list[SubscriptionSummary]
    # Organisation-wide: seats are people (largest plan limit), storage is bought per system (sum).
    seats: Allowance
    storage: Allowance
    # Q5: whether a full storage quota pauses new analyses (otherwise it only warns).
    storage_blocks_at_limit: bool


class LedgerEntryResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    period: str
    kind: str
    bucket: str
    amount: int
    balance_after: int
    task_id: uuid.UUID | None
    reason: str | None
    # For the "Credit activity" labels: "Analysis · <project> · <area>", "Monthly allowance · <plan>".
    project_name: str | None
    aoi_name: str | None
    plan_name: str | None


class LedgerPage(BaseModel):
    items: list[LedgerEntryResponse]
    total: int
    limit: int
    offset: int


class PaymentResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    paid_on: date
    family: str | None
    # plan_period, top_up or reversal.
    purpose: str
    # Whole TZS; negative for a reversal.
    amount: int
    currency: str
    method: str
    reference: str | None
    credits: int | None
    covers_from: date | None
    covers_until: date | None
    reverses_payment_id: uuid.UUID | None
    reversed: bool


class PaymentPage(BaseModel):
    items: list[PaymentResponse]
    total: int
    limit: int
    offset: int


class SubscriptionRequestCreate(BaseModel):
    subscription_id: uuid.UUID
    # top_up (the plan's top-up pack) or upgrade (to plan_key).
    kind: str = Field(pattern="^(top_up|upgrade)$")
    plan_key: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


class SubscriptionRequestResponse(BaseModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    kind: str
    plan_key: str | None
    plan_name: str | None
    credits: int | None
    status: str
    created_at: datetime
    closed_at: datetime | None
    # True when an open request of this kind already existed (nothing new was sent).
    existing: bool = False
