"""
Request/response schemas for the legacy FIRRIS index calculator endpoints
(app/api/v1/endpoints/firas.py). All composite-index endpoints take
already-extracted sample data (named indicator arrays, one value per
sample/pixel) rather than raw imagery — the GEE ingestion/sampling
step that produces this data is a separate, upstream concern (Phase 3
of the engine); these endpoints are the pure-math layer on top of it,
which is why they're synchronous (no Task/Celery involved — this is
fast numpy/pandas work, not a long-running raster job).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class IndicatorDirectionSchema(str, Enum):
    BENEFIT = "benefit"
    COST = "cost"


class IndicatorMatrixRequest(BaseModel):
    """Common shape for any entropy-weighted composite index request."""

    indicators: dict[str, list[float]] = Field(
        ..., description="Indicator name -> one value per sample/pixel. All lists must be the same length."
    )
    directions: dict[str, IndicatorDirectionSchema] | None = Field(
        None, description="Optional per-indicator benefit/cost direction; defaults to benefit."
    )

    @field_validator("indicators")
    @classmethod
    def _validate_shape(cls, value: dict[str, list[float]]) -> dict[str, list[float]]:
        if len(value) < 2:
            raise ValueError("At least 2 indicators are required.")
        lengths = {len(v) for v in value.values()}
        if len(lengths) > 1:
            raise ValueError(f"All indicator arrays must be the same length; got lengths {lengths}.")
        if lengths and next(iter(lengths)) < 2:
            raise ValueError("At least 2 samples/pixels are required.")
        return value


class IndexSummary(BaseModel):
    mean: float
    min: float
    max: float
    dominant_class: str


class CompositeIndexResponse(BaseModel):
    scores: list[float]
    weights: dict[str, float]
    classifications: list[str]
    summary: IndexSummary


class FviRequest(BaseModel):
    social: list[float]
    physical: list[float]
    economic: list[float]

    @field_validator("economic")
    @classmethod
    def _same_length(cls, value: list[float], info) -> list[float]:
        social = info.data.get("social")
        physical = info.data.get("physical")
        if social is not None and physical is not None:
            if not (len(social) == len(physical) == len(value)):
                raise ValueError("social, physical, and economic arrays must be the same length.")
        return value


class CapacitySubindexRequest(BaseModel):
    """Generic request for CPC / EWE / KF / DRE / RC — same shape, different indicator sets."""

    indicators: dict[str, list[float]]

    @field_validator("indicators")
    @classmethod
    def _validate_shape(cls, value: dict[str, list[float]]) -> dict[str, list[float]]:
        if len(value) < 1:
            raise ValueError("At least 1 indicator is required.")
        lengths = {len(v) for v in value.values()}
        if len(lengths) > 1:
            raise ValueError(f"All indicator arrays must be the same length; got lengths {lengths}.")
        return value


class CapacitySubindexResponse(BaseModel):
    scores: list[float]
    weights: dict[str, float]
    summary: IndexSummary


class FiiRequest(BaseModel):
    cpc: list[float]
    ewe: list[float]
    kf: list[float]
    dre: list[float]
    rc: list[float]
    fvi: list[float]


class CriRequest(BaseModel):
    cpc: list[float]
    ewe: list[float]
    kf: list[float]
    dre: list[float]
    rc: list[float]


class FriRequest(BaseModel):
    hazard: list[float]
    exposure: list[float]
    insecurity: list[float]


class FriResponse(BaseModel):
    scores: list[float]
    classifications: list[str]
    summary: IndexSummary
