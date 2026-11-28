"""NOVA ARI console contracts (/api/v1/platform-admin)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.services.billing.bounds import INTEGER_BOUNDS
from app.schemas.billing import LedgerPage, PaymentResponse, PlanLimits, SubscriptionSummary



def _reason():
    return Field(min_length=1, max_length=2000)


class AdminAccess(BaseModel):
    display_name: str
    email: str | None
    organization_name: str | None


class OverviewTiles(BaseModel):
    active_subscriptions: int
    expiring_soon: int
    expiring_soon_days: int
    credits_used_this_month: int
    open_security_alerts: int
    payments_overdue: int
    customers: int
    period: str


class CustomerRowResponse(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    subscription_id: uuid.UUID | None
    family: str | None
    systems: list[str]
    plan_key: str | None
    plan_name: str | None
    is_internal: bool
    status: str | None
    users_used: int
    users_limit: int | None
    active_sessions: int
    session_limit: int | None
    credits_used: int
    credits_available: int
    credits_unlimited: bool
    storage_used: int
    storage_limit: int | None
    ends_at: datetime | None
    renews_on: datetime | None
    # payment_overdue, expiring_soon, new_device, credits_low, storage_high, suspended
    flags: list[str]


class CustomerPage(BaseModel):
    items: list[CustomerRowResponse]
    total: int
    limit: int
    offset: int


class UsageThisPeriod(BaseModel):
    period: str
    analyses_run: int
    data_processed_bytes: int
    api_requests: int
    downloads: int
    download_bytes: int
    registered_devices: int


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str | None
    email: str | None
    role: str
    status: str
    active_sessions: int


class CustomerDetail(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    created_at: datetime
    rows: list[CustomerRowResponse]
    subscriptions: list[SubscriptionSummary]
    usage: UsageThisPeriod
    members: list[MemberResponse]
    open_alerts: int


class AdminLoginEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID
    user_display_name: str | None
    user_email: str | None
    browser: str
    os: str
    device_type: str
    location: str | None
    country_code: str | None
    # Kept 30 days for security, then removed; NOVA ARI only.
    ip_address: str | None
    result: str
    ended_at: datetime | None
    is_new_device: bool
    # This sign-in ended older sessions under the plan's session limit.
    ended_earlier_sessions: int


class AdminLoginPage(BaseModel):
    items: list[AdminLoginEntry]
    total: int
    limit: int
    offset: int
    location_attribution: str | None


def _bounded(name: str):
    low, high = INTEGER_BOUNDS[name]
    return Field(default=None, ge=low, le=high)


class Overrides(BaseModel):
    """Per-contract values (security review L2): typed per field, bounded, no booleans for numbers. Only the
    fields sent are changed; send null to clear one (the plan's value applies again)."""

    model_config = ConfigDict(extra="forbid")

    monthly_credits_override: StrictInt | None = _bounded("monthly_credits")
    seat_limit_override: StrictInt | None = _bounded("seat_limit")
    storage_bytes_override: StrictInt | None = _bounded("storage_bytes")
    session_limit_override: StrictInt | None = _bounded("session_limit")
    refund_on_data_failure_override: StrictBool | None = None


class AddSubscriptionRequest(BaseModel):
    family: Literal["frris_wrris", "megis"]
    plan_key: str = Field(max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    overrides: Overrides | None = None
    reason: str = _reason()


class AddCustomerRequest(AddSubscriptionRequest):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=3, max_length=64)
    # First owner, provisioned by the identity provider's issuer and verified subject (optional).
    owner_issuer: str | None = Field(default=None, max_length=512)
    owner_subject: str | None = Field(default=None, max_length=512)
    owner_email: str | None = Field(default=None, max_length=320)
    owner_name: str | None = Field(default=None, max_length=255)


class CustomerCreated(BaseModel):
    organization_id: uuid.UUID
    subscription_id: uuid.UUID
    owner_user_id: uuid.UUID | None


class StatusChangeRequest(BaseModel):
    status: Literal["active", "suspended", "expired", "canceled"]
    # Optional new end date (needed to reactivate a subscription whose end date has passed).
    ends_at: datetime | None = None
    change_ends_at: bool = False
    reason: str = _reason()


class PlanChangeRequest(BaseModel):
    plan_key: str | None = Field(default=None, max_length=64)
    overrides: Overrides | None = None
    reason: str = _reason()


class RecordPaymentRequest(BaseModel):
    purpose: Literal["plan_period", "top_up"]
    amount: int = Field(gt=0)
    method: Literal["bank_transfer", "mobile_money", "cash", "other"]
    paid_on: date
    reference: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    covers_from: date | None = None
    covers_until: date | None = None
    credits: int | None = Field(default=None, gt=0)


class PaymentRecorded(BaseModel):
    payment: PaymentResponse
    ledger_entry_id: uuid.UUID | None
    replayed: bool


class ReasonRequest(BaseModel):
    reason: str = _reason()


class GrantCreditsRequest(BaseModel):
    credits: int = Field(gt=0, le=10_000)
    reason: str = _reason()


class AdjustCreditsRequest(BaseModel):
    amount: int = Field(ge=-10_000, le=10_000)
    bucket: Literal["monthly", "top_up"] = "top_up"
    reason: str = _reason()


class CreditsChanged(BaseModel):
    ledger_entry_id: uuid.UUID
    remaining: int


class EndSessionsRequest(BaseModel):
    user_id: uuid.UUID | None = None
    reason: str = _reason()


class EndSessionsResponse(BaseModel):
    ended: int


class AdminPaymentResponse(PaymentResponse):
    organization_id: uuid.UUID
    organization_name: str
    note: str | None
    expected_amount: int | None
    recorded_by: str | None


class AdminPaymentPage(BaseModel):
    items: list[AdminPaymentResponse]
    total: int
    limit: int
    offset: int


class AdminPlan(BaseModel):
    key: str
    family: str
    name: str
    is_custom: bool
    is_internal: bool
    unlimited_credits: bool
    limits: PlanLimits
    refund_on_data_failure: bool
    currency: str
    monthly_price: int | None
    top_up_credit_price: int | None
    price_version: int | None
    subscriptions: int


class PriceChangeRequest(BaseModel):
    monthly_price: int | None = Field(default=None, ge=0)
    top_up_credit_price: int | None = Field(default=None, gt=0)
    reason: str = _reason()


class LimitChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seat_limit: StrictInt | None = _bounded("seat_limit")
    monthly_credits: StrictInt | None = _bounded("monthly_credits")
    storage_bytes: StrictInt | None = _bounded("storage_bytes")
    session_limit: StrictInt | None = _bounded("session_limit")
    refund_on_data_failure: StrictBool | None = None
    # Which of the fields above to apply (so a limit can also be set to "no limit").
    fields: list[Literal["seat_limit", "monthly_credits", "storage_bytes", "session_limit",
                         "refund_on_data_failure"]] = Field(min_length=1)
    reason: str = _reason()


class SecurityAlertResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    kind: str
    organization_id: uuid.UUID
    organization_name: str
    user_id: uuid.UUID
    user_display_name: str | None
    user_email: str | None
    detail: dict | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    acknowledge_reason: str | None


class SecurityAlertPage(BaseModel):
    items: list[SecurityAlertResponse]
    total: int
    limit: int
    offset: int


class AuditEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None
    actor: str | None
    action: str
    organization_id: uuid.UUID | None
    organization_name: str | None
    target_type: str | None
    target_id: str | None
    previous: dict | None
    current: dict | None
    reason: str
    request_id: str | None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    limit: int
    offset: int


__all__ = ["LedgerPage"]


class AdminRequest(BaseModel):
    id: uuid.UUID
    created_at: datetime
    organization_id: uuid.UUID
    organization_name: str
    subscription_id: uuid.UUID
    family: str | None
    current_plan: str | None
    kind: str
    plan_key: str | None
    plan_name: str | None
    credits: int | None
    note: str | None
    requested_by: str | None
    status: str
    closed_at: datetime | None
    closed_by: str | None
    close_reason: str | None


class AdminRequestPage(BaseModel):
    items: list[AdminRequest]
    total: int
    limit: int
    offset: int


class CloseRequest(BaseModel):
    outcome: Literal["done", "declined"]
    reason: str = _reason()


class AdminMobilePayment(BaseModel):
    id: uuid.UUID
    created_at: datetime
    organization_id: uuid.UUID
    organization_name: str
    subscription_id: uuid.UUID
    purpose: str
    amount: int
    currency: str
    credits: int | None
    phone: str  # masked
    status: str
    reference: str
    abliner_tx_id: str | None
    abliner_event_tx_id: str | None
    provider_reference: str | None
    failure_code: str | None
    review_reason: str | None
    payment_id: uuid.UUID | None
    resolution: str | None
    resolved_at: datetime | None


class AdminMobilePaymentPage(BaseModel):
    items: list[AdminMobilePayment]
    total: int
    limit: int
    offset: int


class ResolveReviewRequest(BaseModel):
    resolution: Literal["credited_manually", "no_action"]
    reason: str = _reason()


class IntegrationResponse(BaseModel):
    """Read-only. There is no field that could carry a secret or a value."""
    name: Literal["abliner", "gee", "auth0"]
    label: str
    configured: bool
    # Names of missing settings (never their values).
    missing: list[str]
    # Abliner only: whether customer payments are switched on (ABLINER_PAYMENTS_ENABLED).
    enabled: bool | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_code: str | None
    last_webhook_at: datetime | None
    last_webhook_event: str | None
    last_test_at: datetime | None
    last_test_result: str | None


class IntegrationTestResult(BaseModel):
    name: str
    ok: bool
    # connected, reachable, not_configured, timeout, unauthorized, ...: a code, never a response body.
    result: str
