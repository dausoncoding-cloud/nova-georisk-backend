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
