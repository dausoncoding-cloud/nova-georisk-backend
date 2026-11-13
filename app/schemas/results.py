"""Browser-safe persistent analysis result contracts."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from app.schemas.firris_evidence import ValidationDashboard, DecisionSupportDashboard
from app.schemas.result_delivery import ResultAnalytics, ResultInterpretation


class ResultProductResponse(BaseModel):
    key: str
    label: str
    url: str
    media_type: str
    delivery_type: str
    format: str
    gis_metadata: dict | None = None
    artifact_type: Literal["raster", "vector", "preview", "metadata", "report", "package"]
    role: Literal["product", "export"]
    product_key: str | None = None
    schema_version: str
    result_version: int
    file_size_bytes: int | None = None
    checksum_sha256: str | None = None
    # Plan item 2.5: curated download group, computed at read time.
    deliverable_group: Literal["client_deliverable", "gis_data", "figures", "audit"] | None = None


class ResultLayerResponse(BaseModel):
    key: str
    label: str
    product_key: str
    layer_type: Literal["raster", "vector"]
    crs: str | None = None
    bounding_box: dict[str, float] | None = None
    spatial_resolution: dict[str, Any] | None = None
    units: str | None = None
    nodata: float | int | str | None = None
    legend: dict[str, Any] | list[Any] | None = None
    renderable: bool
    rendering_reason: str | None = None
    available_delivery_types: list[str]
    planned_delivery_types: list[str]
    artifact_keys: list[str]
    display_bounds_wgs84: dict[str, float] | None = None
    temporal_metadata: dict[str, Any] | None = None


class OverviewHeadline(BaseModel):
    text: str
    flood_candidate_area_km2: float | None
    percent_of_valid: float | None
    valid_area_km2: float | None
    target_period: str | None
    baseline_period: str | None


class MissingCellsByBand(BaseModel):
    band: str
    cells: int
    pct_of_aoi: float | None
    affects_admission: bool


class AreaAccounting(BaseModel):
    aoi_cells: int | None
    valid_cells: int | None
    excluded_cells: int | None
    valid_area_km2: float | None
    aoi_area_km2_estimate: float | None
    excluded_area_km2_estimate: float | None
    valid_pct_of_aoi: float | None
    flood_candidate_area_km2: float | None
    flood_candidate_pct_of_valid: float | None
    flood_candidate_pct_of_aoi: float | None
    missing_cells_by_band: list[MissingCellsByBand]
    method_note: str


class QualityGateRow(BaseModel):
    name: str
    threshold: str
    observed: str | None
    status: Literal["pass", "fail", "not_recorded", "not_applicable"]


class DataSourceRow(BaseModel):
    dataset: str
    role: str
    resolution: str
    scene_dates: list[str]
    credit: str


class ResultOverview(BaseModel):
    """Plan item 2.3: read-time overview computed from stored summary and provenance."""
    headline: OverviewHeadline
    area_accounting: AreaAccounting
    quality_gates: list[QualityGateRow]
    data_sources: list[DataSourceRow]
    limitations: list[str]


class ResultResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    aoi_id: uuid.UUID | None
    engine_key: str
    result_type: str
    version: int
    summary: dict | None
    analytics: ResultAnalytics | None = None
    interpretation: ResultInterpretation | None = None
    validation_dashboard: ValidationDashboard | None = None
    # Read-time notice for results produced before firris-science-2; never stored.
    interpretation_notice: str | None = None
    overview: ResultOverview | None = None
    decision_support: DecisionSupportDashboard | None = None
    provenance: dict | None
    products: list[ResultProductResponse]
    layers: list[ResultLayerResponse]
    exports: list[ResultProductResponse]
    created_at: datetime
    updated_at: datetime


class ResultPage(BaseModel):
    items: list[ResultResponse]
    total: int
    limit: int
    offset: int
