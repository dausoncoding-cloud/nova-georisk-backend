"""Explicit FIRRIS module-to-source bindings; no implicit dataset discovery."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.source_data import TemporalCoverage


FIRRISModule = Literal["hazard", "exposure", "vulnerability", "insecurity", "risk", "resilience", "flood_depth", "flood_velocity", "flood_hazard_product", "flood_aep", "flood_return_period", "flood_duration", "flood_susceptibility", "flood_hazard_zonation", "satellite_preprocessing"]


class RasterGrid(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    crs: str
    west: float
    south: float
    east: float
    north: float
    width: int = Field(gt=0, le=10000)
    height: int = Field(gt=0, le=10000)

    @model_validator(mode="after")
    def check_grid(self):
        if self.west >= self.east or self.south >= self.north or self.width * self.height > 25_000_000:
            raise ValueError("Raster grid bounds/cell count are invalid")
        return self


class HazardProcessingOptions(BaseModel):
    """Declared spatial support for the spec's stream-length / area indicator."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    drainage_window_m: float = Field(gt=0)


class ExposureProcessingOptions(BaseModel):
    """Selected *index-class* zone, not an observed inundation footprint."""

    model_config = ConfigDict(extra="forbid")
    hazard_min_level: Literal["moderate", "high", "extreme"]


class DurationProcessingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    temporal_resolution_hours: float = Field(gt=0, le=168)
    gap_policy: Literal["reject"] = "reject"


class SatellitePreprocessingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raster_alignment: Literal["nearest_no_upsampling"]
    climate_interpolation: Literal["reviewed_station_idw"]
    terrain_products: list[Literal["slope", "aspect", "curvature", "flow_direction", "flow_accumulation", "twi"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_products(self):
        if len(set(self.terrain_products)) != len(self.terrain_products):
            raise ValueError("Terrain products must be unique")
        return self


class SourceBoundAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID
    aoi_id: uuid.UUID
    module: FIRRISModule
    sources: dict[str, uuid.UUID] = Field(default_factory=dict)
    upstream_results: dict[str, uuid.UUID] = Field(default_factory=dict)
    period: TemporalCoverage
    target_grid: RasterGrid | None = None
    hazard_options: HazardProcessingOptions | None = None
    exposure_options: ExposureProcessingOptions | None = None
    duration_options: DurationProcessingOptions | None = None
    satellite_options: SatellitePreprocessingOptions | None = None

    @model_validator(mode="after")
    def check_module_options(self):
        if (self.module == "hazard") != (self.hazard_options is not None):
            raise ValueError("Hazard requires explicit drainage spatial support; other modules cannot use hazard options")
        if (self.module == "exposure") != (self.exposure_options is not None):
            raise ValueError("Exposure requires an explicit Hazard index class threshold")
        if (self.module == "flood_duration") != (self.duration_options is not None):
            raise ValueError("Flood Duration requires a declared temporal resolution and reject-on-gap policy")
        if (self.module == "satellite_preprocessing") != (self.satellite_options is not None):
            raise ValueError("Satellite preprocessing requires explicit alignment/interpolation policies")
        return self


class SourceBindingValidationResponse(BaseModel):
    module: FIRRISModule
    source_ids: dict[str, uuid.UUID]
    analysis_ready: bool
    executable: bool
    reason: str | None = None
