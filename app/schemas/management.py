import uuid
from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.identity import MembershipRole
from app.schemas.source_data import SourceReadinessReview


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ProvisionMembership(Strict):
    issuer: str = Field(min_length=8, max_length=512)
    subject: str = Field(min_length=1, max_length=512)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    role: MembershipRole
    evidence_reference: str = Field(min_length=3, max_length=500)

    @field_validator('issuer','subject','email','display_name','evidence_reference')
    @classmethod
    def no_controls(cls,value):
        if value is not None and any(ord(c)<32 for c in value):raise ValueError('Control characters are not permitted.')
        return value


class MembershipChange(Strict):
    role: MembershipRole
    status: Literal['active', 'disabled', 'removed']


class MemberView(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    display_name: str | None
    email: str | None
    issuer: str
    subject: str
    role: MembershipRole
    status: str
    user_active: bool
    updated_at: datetime
    created_at: datetime


class MemberPage(BaseModel):
    items: list[MemberView]
    total: int


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    actor_user_id: uuid.UUID
    target_user_id: uuid.UUID | None
    action: str
    previous: dict | None = Field(json_schema_extra={"anyOf": [{"type": "object", "additionalProperties": True}, {"type": "null"}]})
    current: dict = Field(json_schema_extra={"additionalProperties": True})
    created_at: datetime
    request_id: str | None


class AuditPage(BaseModel):
    items: list[AuditView]
    total: int


class DatasetDraft(Strict):
    title: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=80)
    aoi_id: uuid.UUID | None = None
    replaces: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, json_schema_extra={"additionalProperties": True})


class DatasetView(BaseModel):
    id: uuid.UUID
    series_id: uuid.UUID
    version: int
    project_id: uuid.UUID
    aoi_id: uuid.UUID | None
    uploader_id: uuid.UUID
    source_dataset_id: uuid.UUID | None
    title: str
    category: str
    format: str
    status: str
    sha256: str
    size_bytes: int
    metadata: dict = Field(json_schema_extra={"additionalProperties": True})
    validation: dict = Field(json_schema_extra={"additionalProperties": True})
    created_at: datetime


class DatasetPage(BaseModel):
    items: list[DatasetView]
    total: int


class DatasetMetadata(Strict):
    metadata: dict[str, Any] = Field(json_schema_extra={"additionalProperties": True})
    aoi_id: uuid.UUID | None = None


class DatasetReview(Strict):
    decision: Literal['approve', 'reject', 'revoke']
    reason: str = Field(min_length=5, max_length=1000)
    review: SourceReadinessReview | None = None


class DatasetEligibility(BaseModel):
    dataset_id: uuid.UUID
    approved: bool
    compatible: bool
    reasons: list[str]
    candidate_modules: list[str]
    note: str


class InvitationView(BaseModel):
    id: uuid.UUID
    email: str
    role: MembershipRole
    created_at: datetime
    expires_at: datetime
    status: Literal['pending','expired','redeemed']
    access_granted: bool | None
    policy_note: str
