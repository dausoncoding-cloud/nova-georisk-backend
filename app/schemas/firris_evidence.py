"""Explicit externally supplied evidence/policy contracts; no scientific defaults."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator
from app.schemas.strict import StrictModel


class ValidationDefinition(StrictModel):
    quantity_id: str = Field(min_length=1, max_length=64)
    definition: str = Field(min_length=10, max_length=1000)
    value_units: str = Field(min_length=1, max_length=64)
    comparison_reference: str = Field(min_length=3, max_length=512)
    model_reference: str | None = Field(default=None, min_length=3, max_length=512)
    evaluation_scope: Literal['declared_holdout', 'reviewed_independent', 'not_independent']
    training_dataset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    class_labels: dict[str, str] | None = None
    decision_threshold: float | None = Field(default=None, ge=0, le=1)
    hotspot_absolute_error_threshold: float | None = Field(default=None, gt=0)
    hotspot_policy_reference: str | None = Field(default=None, min_length=3)
    uncertainty_kind: Literal['standard_deviation', 'variance', 'absolute_interval_half_width'] | None = None
    confidence_level: float | None = Field(default=None, gt=0, lt=1)
    fold_definitions: dict[str, str] | None = None

    @model_validator(mode='after')
    def definitions(self):
        if (self.hotspot_absolute_error_threshold is None) != (self.hotspot_policy_reference is None):
            raise ValueError('Hotspots require a paired sourced threshold and policy reference')
        if self.class_labels is not None and (set(self.class_labels) != {'0', '1'} or any(not label.strip() for label in self.class_labels.values()) or len(set(self.class_labels.values())) != 2):
            raise ValueError('Current FIRRIS classification supports two explicitly named binary classes only')
        if self.fold_definitions is not None and (not self.fold_definitions or any(not key.isdecimal() or str(int(key)) != key or not label.strip() for key, label in self.fold_definitions.items())):
            raise ValueError('Fold codes require canonical nonnegative integers and sourced definitions')
        if (self.uncertainty_kind == 'absolute_interval_half_width') != (self.confidence_level is not None):
            raise ValueError('Interval uncertainty requires an explicit confidence level; other measures cannot use it')
        return self


class ImpactDefinition(StrictModel):
    basis: Literal['observed', 'externally_modelled']
    definition: str = Field(min_length=10, max_length=1000)
    evidence_reference: str = Field(min_length=3, max_length=512)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    model_reference: str | None = Field(default=None, min_length=3)

    @model_validator(mode='after')
    def model(self):
        if (self.basis == 'externally_modelled') != (self.model_reference is not None):
            raise ValueError('Modelled impacts require a sourced model reference; observed impacts cannot claim one')
        return self


class DSSMetricDefinition(StrictModel):
    domain: Literal['community', 'infrastructure', 'event', 'kpi']
    units: str = Field(min_length=1, max_length=64)
    definition: str = Field(min_length=10, max_length=1000)
    evidence_reference: str = Field(min_length=3, max_length=512)


class AlertRule(StrictModel):
    sensor_id: str = Field(min_length=1, max_length=128)
    operator: Literal['gt', 'ge', 'lt', 'le']
    threshold: float
    units: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)


class LiveFeedPolicy(StrictModel):
    policy_reference: str = Field(min_length=3, max_length=512)
    max_lateness_seconds: int = Field(gt=0, le=31_536_000)
    max_future_skew_seconds: int = Field(ge=0, le=3600)
    max_nowcast_horizon_seconds: int = Field(ge=0, le=604800)
    nowcast_model_references: list[str] = Field(default_factory=list, max_length=50)
    alert_rules: dict[str, AlertRule] = Field(default_factory=dict, max_length=100)

    @model_validator(mode='after')
    def references(self):
        if any(not item.strip() for item in self.nowcast_model_references):
            raise ValueError('Nowcast model references cannot be blank')
        return self


class LiveEventRequest(StrictModel):
    policy_dataset_id: uuid.UUID
    event_id: str = Field(min_length=1, max_length=128)
    sensor_id: str = Field(min_length=1, max_length=128)
    kind: Literal['observation', 'nowcast']
    quality_flag: Literal['valid']
    value: float
    units: str = Field(min_length=1, max_length=64)
    valid_at: datetime
    issued_at: datetime
    source_record_reference: str = Field(min_length=3, max_length=512)
    model_reference: str | None = Field(default=None, min_length=3, max_length=512)

    @model_validator(mode='after')
    def dates(self):
        if not self.valid_at.tzinfo or not self.issued_at.tzinfo:
            raise ValueError('Live timestamps must be timezone-aware')
        if self.kind == 'observation' and (self.valid_at != self.issued_at or self.model_reference is not None):
            raise ValueError('Observations must retain their actual observation instant and cannot claim a nowcast model')
        if self.kind == 'nowcast' and (self.model_reference is None or self.valid_at < self.issued_at):
            raise ValueError('Nowcasts require an explicit model and ordered issue/valid times')
        return self


class LiveFeedbackRequest(StrictModel):
    verdict: Literal['confirmed', 'rejected', 'inconclusive']
    notes: str = Field(min_length=3, max_length=2000)
    evidence_references: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def references(self):
        if any(not item.strip() for item in self.evidence_references):
            raise ValueError('Feedback evidence cannot be blank')
        return self


class LiveEventResponse(StrictModel):
    id: uuid.UUID
    sequence: int
    payload: dict
    received_at: datetime
    source_snapshot: dict
    alerts: list[dict]
    delivery_status: Literal['protected_feed_only'] = 'protected_feed_only'


class LiveEventPage(StrictModel):
    items: list[LiveEventResponse]
    next_cursor: int
    external_delivery: Literal['unavailable_not_configured'] = 'unavailable_not_configured'


class LiveFeedbackResponse(StrictModel):
    model_config = {"from_attributes": True, "extra": "forbid"}
    id: uuid.UUID
    event_id: uuid.UUID
    verdict: str
    notes: str
    evidence_references: list[str]
    created_at: datetime
    actor_id: uuid.UUID | None


class ValidationDashboard(StrictModel):
    kind: Literal['continuous', 'binary']
    metrics: dict
    availability: dict[str, dict]
    plots: list[str]
    scope: str
    units: str
    limitations: list[str]


class DecisionSupportDashboard(StrictModel):
    tables: dict[str, list[dict]]
    source_identity: dict
    limitations: list[str]
