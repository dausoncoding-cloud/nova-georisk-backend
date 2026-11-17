"""Engine-neutral persistent analysis contracts."""
from __future__ import annotations

import uuid
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import TaskStatusResponse
from app.services.ml.contracts import ClassifierType


class FIRRISProduct(str, Enum):
    FLOOD_EXTENT = "flood_extent"
    FLOOD_DEPTH = "flood_depth"
    FLOOD_VELOCITY = "flood_velocity"
    FLOOD_HAZARD = "flood_hazard"
    FLOOD_PROBABILITY = "flood_probability"
    FLOOD_DURATION = "flood_duration"
    FLOOD_EXPOSURE = "flood_exposure"
    FLOOD_VULNERABILITY = "flood_vulnerability"
    FLOOD_RISK = "flood_risk"
    FLOOD_SUSCEPTIBILITY = "flood_susceptibility"
    FLOOD_HAZARD_ZONATION = "flood_hazard_zonation"


class BoundingBox(BaseModel):
    west: float
    south: float
    east: float
    north: float

    @model_validator(mode="after")
    def ordered(self) -> "BoundingBox":
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("Bounding box coordinates are not ordered.")
        return self


class SpatialResolution(BaseModel):
    x: float = Field(gt=0)
    y: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)


class GISMetadata(BaseModel):
    crs: str = Field(min_length=1, max_length=128)
    datum: str | None = Field(default=None, max_length=128)
    projection: str | None = Field(default=None, max_length=128)
    bounding_box: BoundingBox
    spatial_resolution: SpatialResolution | None = None
    acquisition_date: date | None = None
    producer: str = Field(default="NOVA GeoRisk", min_length=1, max_length=255)
    engine_version: str | None = Field(default=None, max_length=64)


class AnalysisDateRange(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> "AnalysisDateRange":
        if self.start >= self.end:
            raise ValueError("Date range start must be before end.")
        return self


class SatelliteSourceConfig(BaseModel):
    provider: Literal["prepared", "gee"] = "prepared"
    datasets: list[str] = Field(default_factory=list)
    target_period: AnalysisDateRange | None = None
    baseline_period: AnalysisDateRange | None = None
    max_cloud_pct: float = Field(default=20, ge=0, le=100)
    minimum_valid_coverage_pct: float = Field(default=70, ge=0, le=100)
    scale: float = Field(default=30, ge=1, le=1000)
    target_crs: str = Field(default="EPSG:4326", min_length=1, max_length=128)
    dem_source: Literal["SRTM", "ALOS"] = "SRTM"
    date_mode: Literal["pre-post", "seasonal", "annual"] = "pre-post"
    features: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def gee_periods_required(self) -> "SatelliteSourceConfig":
        if self.provider == "gee" and (self.target_period is None or self.baseline_period is None):
            raise ValueError("GEE source requires target_period and baseline_period.")
        optical = sorted(set(self.features) & {"ndvi", "mndwi", "ndbi", "ndwi", "ndmi"})
        if self.provider == "gee" and optical:
            raise ValueError(f"Optical indices cannot be FRRIS model features: {optical}. "
                             "Sentinel-2 is the independent accuracy reference; use SAR, terrain and rainfall features.")
        if self.provider == "gee":
            baseline, target = self.baseline_period, self.target_period
            if baseline.end > target.start:
                raise ValueError("Baseline must precede target without overlap")
            if self.date_mode == "annual" and any((p.start.month, p.start.day, p.end.month, p.end.day, p.end.year - p.start.year) != (1, 1, 1, 1, 1) for p in (baseline, target)):
                raise ValueError("Annual mode requires full end-exclusive calendar years")
            if self.date_mode == "seasonal" and (baseline.start.month, baseline.start.day, baseline.end.month, baseline.end.day) != (target.start.month, target.start.day, target.end.month, target.end.day):
                raise ValueError("Seasonal mode requires matching calendar windows")
        return self


class FIRRISPreprocessingConfig(BaseModel):
    preview_enhancement: bool = False
    cloud_mask: bool = True
    sar_speckle_filter: bool = True
    sar_speckle_radius_m: int = Field(default=50, ge=1, le=500)
    normalize_projection: bool = True
    clip_to_aoi: bool = True


class FIRRISSamplingConfig(BaseModel):
    strategy: Literal["stratified_random", "simple_random"] = "stratified_random"
    sample_size: int = Field(default=5000, ge=10, le=1_000_000)
    min_per_class: int = Field(default=30, ge=2, le=100_000)
    train_fraction: float = Field(default=0.70, ge=0.5, lt=1)
    random_seed: int = 12345


class FIRRISModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm: ClassifierType = "random_forest"
    comparison_algorithms: list[ClassifierType] = Field(default_factory=list, max_length=5)
    version: str = Field(default="1.0", min_length=1, max_length=64)
    n_estimators: int = Field(default=200, ge=10, le=2000)

    @model_validator(mode="after")
    def unique_comparisons(self):
        if len(set(self.comparison_algorithms)) != len(self.comparison_algorithms) or self.algorithm in self.comparison_algorithms:
            raise ValueError("Comparison algorithms must be unique and exclude the explicitly selected algorithm")
        return self


class FIRRISPostprocessingConfig(BaseModel):
    """Optional categorical generalization; raw scientific predictions are preserved."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operations: list[Literal["majority", "opening", "closing"]] = Field(default_factory=list, max_length=3)
    policy_reference: str | None = Field(default=None, min_length=3, max_length=512)
    window_pixels: Literal[3, 5, 7] = 3

    @model_validator(mode="after")
    def explicit_policy(self):
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("Cleanup operations must be unique")
        if self.operations and not self.policy_reference:
            raise ValueError("Opt-in cleanup requires an explicit policy reference")
        if not self.operations and self.policy_reference is not None:
            raise ValueError("A cleanup policy reference requires explicit operations")
        return self


class FIRRISContextConfig(BaseModel):
    """Opt-in context layers next to the flood map (Depth & Exposure module). They never change the flood map."""
    model_config = ConfigDict(extra="forbid")
    modelled_flood_hazard: bool = Field(default=False, description=(
        "Add the GloFAS v2.1 modelled river-flood hazard (depth for return periods 10-500 years) as context. "
        "Earth Engine source only."))
    flood_exposure: bool = Field(default=False, description=(
        "Add the estimated exposure (WorldPop R2025A people, Open Buildings v3 buildings) inside the observed flood "
        "extent and inside each modelled return-period zone. Needs the modelled flood hazard."))


class FIRRISSatelliteWorkflowConfig(BaseModel):
    source: SatelliteSourceConfig
    preprocessing: FIRRISPreprocessingConfig = Field(default_factory=FIRRISPreprocessingConfig)
    postprocessing: FIRRISPostprocessingConfig = Field(default_factory=FIRRISPostprocessingConfig)
    sampling: FIRRISSamplingConfig = Field(default_factory=FIRRISSamplingConfig)
    model: FIRRISModelConfig = Field(default_factory=FIRRISModelConfig)
    quality: dict[str, Any] = Field(default_factory=dict)
    feature_layers: dict[str, list[list[float]]] | None = None
    label_layer: list[list[int]] | None = None
    valid_mask: list[list[bool]] | None = None
    label_source: str | None = Field(default=None, max_length=512)
    context: FIRRISContextConfig = Field(default_factory=FIRRISContextConfig)

    @model_validator(mode="after")
    def context_needs_earth_engine(self):
        if self.context.modelled_flood_hazard and self.source.provider != "gee":
            raise ValueError("The modelled flood hazard (GloFAS) needs the Earth Engine source")
        if self.context.flood_exposure and not self.context.modelled_flood_hazard:
            raise ValueError("The exposure estimate uses the modelled hazard zones: switch on the modelled flood hazard too")
        return self


class FIRRISAnalysisParameters(BaseModel):
    """Typed universal workflow plus backwards-compatible direct product inputs."""

    model_config = ConfigDict(extra="allow")
    workflow: FIRRISSatelliteWorkflowConfig | None = None


class AnalysisSubmitRequest(BaseModel):
    project_id: uuid.UUID
    aoi_id: uuid.UUID
    operation: str = Field(default="flood_mapping", pattern="^flood_mapping$")
    products: list[FIRRISProduct] = Field(min_length=1)
    parameters: FIRRISAnalysisParameters
    gis_metadata: GISMetadata

    @model_validator(mode="after")
    def unique_products(self) -> "AnalysisSubmitRequest":
        if len(set(self.products)) != len(self.products):
            raise ValueError("Each product may be requested only once.")
        return self


class AnalysisPreflightIssue(BaseModel):
    """A blocking reason or a warning, in plain language."""
    code: str
    message: str
    period: Literal["target", "baseline"] | None = None


class AnalysisPreflightPeriod(BaseModel):
    start: date
    end: date
    sentinel1_pass_dates: list[date] = Field(default_factory=list)
    relative_orbits: list[int] = Field(default_factory=list)
    nearest_pass_before: date | None = None
    nearest_pass_after: date | None = None
    sentinel2_compliant_scenes: int | None = None
    # Same eligibility and AOI-coverage rule as the run's independent Sentinel-2 reference.
    sentinel2_tiles: list[str] = Field(default_factory=list)
    sentinel2_dates: list[date] = Field(default_factory=list)
    sentinel2_aoi_coverage_pct: float | None = None
    sentinel2_summary: str | None = None


class AnalysisPreflightCapacity(BaseModel):
    scale_m: float
    bbox_pixels: int
    estimated_request_bytes: int
    limit_bytes: int
    ratio: float
    suggested_scale_m: float | None = None


class AnalysisPreflightResponse(BaseModel):
    """Metadata-only availability check (plan items 4.1, 4.4, 4.6). Never creates a task or result."""
    ok: bool
    target: AnalysisPreflightPeriod | None = None
    baseline: AnalysisPreflightPeriod | None = None
    shared_relative_orbits: list[int] = Field(default_factory=list)
    capacity: AnalysisPreflightCapacity | None = None
    blocking: list[AnalysisPreflightIssue] = Field(default_factory=list)
    warnings: list[AnalysisPreflightIssue] = Field(default_factory=list)


class AnalysisSubmitResponse(BaseModel):
    task: TaskStatusResponse
    # Plan 4.1: non-blocking preflight findings at submission (e.g. no compliant Sentinel-2 scene).
    preflight_warnings: list[AnalysisPreflightIssue] = Field(default_factory=list)


class DeliveryRepresentation(BaseModel):
    kind: Literal["raster", "vector", "preview", "metadata"]
    format: str
    status: Literal["available", "planned"]
    media_type: str | None = None
    renderable: bool = False


class EngineProductDefinition(BaseModel):
    key: str
    label: str
    available_delivery_types: list[str]
    planned_delivery_types: list[str]
    representations: list[DeliveryRepresentation]


class EngineExecutionContract(BaseModel):
    engine_key: str
    engine_name: str
    engine_version: str
    operations: list[str]
    products: list[EngineProductDefinition]
