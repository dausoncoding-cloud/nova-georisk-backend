"""
Shared Pydantic contracts: CRS/AOI geometry, date ranges, task status.

These mirror the "Universal API JSON Schema" style shown in Doc 0 §6 so
the BFF has one consistent payload shape to work against for every engine.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AOISourceType(str, Enum):
    DRAWN_POLYGON = "drawn_polygon"
    SHAPEFILE = "shapefile"
    GEOJSON = "geojson"
    KML = "kml"
    GPKG = "gpkg"
    ADMIN_BOUNDARY = "admin_boundary"
    RECTANGLE_FROM_COORDS = "rectangle_from_coords"


class GeoJSONGeometry(BaseModel):
    """Minimal GeoJSON geometry envelope (Polygon / MultiPolygon)."""

    type: str = Field(..., examples=["Polygon", "MultiPolygon"])
    coordinates: list = Field(...)


class AOICreateRequest(BaseModel):
    project_id: uuid.UUID
    name: str = "Untitled AOI"
    source_type: AOISourceType = AOISourceType.DRAWN_POLYGON
    geometry: GeoJSONGeometry
    crs: str = "EPSG:4326"


class AOIUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class AOIStats(BaseModel):
    area_m2: float
    area_hectares: float
    area_km2: float
    perimeter_m: float


class AOIResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    source_type: AOISourceType
    geometry: GeoJSONGeometry
    crs: str = "EPSG:4326"
    stats: AOIStats
    created_at: datetime
    source_lineage: dict | None = None


class AdministrativeBoundaryChoice(BaseModel):
    dataset_id: uuid.UUID
    spatial_unit_id: str
    name: str
    level: str
    source_id: str
    source_sha256: str
    source_version: datetime
    producer: str
    custodian: str
    licence_identifier: str
    permitted_use: str
    redistribution: str
    observed_at: datetime
    positional_uncertainty_m: float
    reviewed_at: datetime
    geometry: GeoJSONGeometry


class AdministrativeBoundaryPage(BaseModel):
    items: list[AdministrativeBoundaryChoice]
    total: int
    limit: int
    offset: int


class AdministrativeBoundaryAOICreate(BaseModel):
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    spatial_unit_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)


class AOIPage(BaseModel):
    items: list[AOIResponse]
    total: int
    limit: int
    offset: int


class GeoPackageLayer(BaseModel):
    name: str
    geometry_type: str


class GeoPackageLayerList(BaseModel):
    layers: list[GeoPackageLayer]


class DateRangeMode(str, Enum):
    SEASONAL = "seasonal"
    ANNUAL = "annual"
    PRE_EVENT = "pre_event"
    POST_EVENT = "post_event"


class DateRange(BaseModel):
    mode: DateRangeMode = DateRangeMode.ANNUAL
    start_date: datetime
    end_date: datetime


class TaskStatusEnum(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ResultReference(BaseModel):
    id: uuid.UUID
    result_type: str
    version: int
    created_at: datetime


class TaskStatusResponse(BaseModel):
    id: uuid.UUID
    # Retained for compatibility with the original task-status response.
    task_id: uuid.UUID
    project_id: uuid.UUID
    engine_key: str
    aoi_id: uuid.UUID | None = None
    task_type: str
    status: TaskStatusEnum
    progress_pct: int = 0
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_summary: str | None = None
    # Retained as a safe alias; raw worker exception text is never returned.
    error_message: str | None = None
    result_payload: dict | None = None
    result_reference: ResultReference | None = None


class TaskPage(BaseModel):
    items: list[TaskStatusResponse]
    total: int
    limit: int
    offset: int
