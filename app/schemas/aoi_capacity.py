"""Area playground capacity check (P6): request and response of POST /api/v1/aois/capacity."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analyses import AnalysisPreflightCapacity
from app.schemas.common import GeoJSONGeometry


class AOICapacityRequest(BaseModel):
    geometry: GeoJSONGeometry
    scale_m: float = Field(30.0, ge=10, le=1000, description="Output resolution in metres (the analysis default is 30 m).")
    trim_center: list[float] | None = Field(None, min_length=2, max_length=2,
                                            description="Centre [longitude, latitude] for the trimmed box; default: the centre of the area's bounding box.")


class AOICapacityPart(BaseModel):
    geometry: GeoJSONGeometry
    area_km2: float
    bbox: list[float] = Field(..., description="[west, south, east, north] in EPSG:4326")
    capacity: AnalysisPreflightCapacity


class AOICapacityTrim(AOICapacityPart):
    box: list[float] = Field(..., description="The largest box that fits, [west, south, east, north]; geometry is the area inside it.")


class AOICapacitySplit(BaseModel):
    rows: int
    cols: int
    parts: list[AOICapacityPart]


class AOICapacityCoarser(BaseModel):
    scale_m: float
    capacity: AnalysisPreflightCapacity


class AOICapacityResponse(BaseModel):
    status: Literal["fits", "near", "over"]
    message: str
    area_km2: float
    bbox: list[float]
    bbox_km2: float
    capacity: AnalysisPreflightCapacity
    near_ratio: float = Field(..., description="Share of the limit from which an area is reported as close to the limit.")
    trim: AOICapacityTrim | None = None
    split: AOICapacitySplit | None = None
    coarser: AOICapacityCoarser | None = None
