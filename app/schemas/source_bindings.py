"""Explicit FIRRIS module-to-source bindings; no implicit dataset discovery."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.source_data import TemporalCoverage, ProximityPolicy


FIRRISModule = Literal["hazard", "exposure", "vulnerability", "insecurity", "risk", "resilience", "flood_depth", "flood_velocity", "flood_hazard_product", "flood_aep", "flood_return_period", "flood_duration", "flood_susceptibility", "flood_hazard_zonation", "satellite_preprocessing", "flood_change", "rainfall_interpolation", "river_stage", "feature_proximity", "watershed", "historical_frequency", "predictor_mlr", "soil_infiltration", "continuous_validation", "classification_validation", "decision_support", "prediction_outputs"]


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



class RainfallInterpolationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    method: Literal["idw", "ordinary_kriging"]
    power: float | None = Field(default=None, gt=0, le=3)
    variogram_model: Literal["spherical", "exponential", "gaussian"] | None = None

    @model_validator(mode="after")
    def applicable_options(self):
        if self.method == "idw" and self.variogram_model is not None:
            raise ValueError("Variogram model is only applicable to ordinary Kriging")
        if self.method == "ordinary_kriging" and self.power is not None:
            raise ValueError("IDW power is only applicable to IDW")
        return self


class ProximityProcessingOptions(ProximityPolicy):
    """Must exactly match the reviewed policy bound to both geometry sources."""


class PredictorModelOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    response: str = Field(min_length=1)
    predictor_order: list[str] = Field(min_length=1, max_length=64)
    vif_limit: float = Field(gt=1, le=100)
    holdout_fraction: float = Field(gt=0, lt=0.5)
    split_policy: Literal["chronological"] = "chronological"

    @model_validator(mode="after")
    def unique_predictors(self):
        if len(set(self.predictor_order)) != len(self.predictor_order) or self.response in self.predictor_order:
            raise ValueError("Predictors must be unique and exclude the response")
        if any(not key for key in self.predictor_order):
            raise ValueError("Predictor names cannot be blank")
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
    rainfall_options: RainfallInterpolationOptions | None = None
    predictor_options: PredictorModelOptions | None = None
    proximity_options: ProximityProcessingOptions | None = None

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
        if (self.module == "rainfall_interpolation") != (self.rainfall_options is not None):
            raise ValueError("Rainfall interpolation requires explicit method options")
        if (self.module == "predictor_mlr") != (self.predictor_options is not None):
            raise ValueError("Predictor MLR requires explicit response, ordering, VIF and holdout policies")
        if (self.module == "feature_proximity") != (self.proximity_options is not None):
            raise ValueError("Feature proximity requires explicit reviewed normalization and directions")
        return self


class SourceBindingValidationResponse(BaseModel):
    module: FIRRISModule
    source_ids: dict[str, uuid.UUID]
    analysis_ready: bool
    executable: bool
    reason: str | None = None
