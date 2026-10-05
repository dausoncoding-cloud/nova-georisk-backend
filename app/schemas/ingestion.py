"""Request/response schemas for the ingestion-trigger endpoints."""
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, field_validator


class ScreeningAtlasRequest(BaseModel):
    project_id: uuid.UUID
    aoi_id: uuid.UUID
    target_start: date
    target_end: date
    baseline_start: date
    baseline_end: date

    @field_validator("target_end")
    @classmethod
    def _target_range_valid(cls, value: date, info) -> date:
        start = info.data.get("target_start")
        if start is not None and value <= start:
            raise ValueError("target_end must be after target_start.")
        return value

    @field_validator("baseline_end")
    @classmethod
    def _baseline_range_valid(cls, value: date, info) -> date:
        start = info.data.get("baseline_start")
        if start is not None and value <= start:
            raise ValueError("baseline_end must be after baseline_start.")
        return value


class TaskTriggerResponse(BaseModel):
    task_id: uuid.UUID
    status: str
