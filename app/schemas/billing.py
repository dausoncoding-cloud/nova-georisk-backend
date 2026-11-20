"""Customer-facing subscription and credit contracts."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


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


class SubscriptionSummary(BaseModel):
    id: uuid.UUID
    family: str
    plan_key: str | None
    plan_name: str | None
    status: str
    status_label: str
    starts_at: datetime | None
    ends_at: datetime | None
    engines: list[str]
    credits: CreditSummary
    can_submit: bool
    block_code: str | None
    block_message: str | None


class BillingSummaryResponse(BaseModel):
    enforcement_enabled: bool
    subscriptions: list[SubscriptionSummary]


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


class LedgerPage(BaseModel):
    items: list[LedgerEntryResponse]
    total: int
    limit: int
    offset: int
