"""
Sampling strategy schema — mirrors the "Universal API JSON Schema"
in Doc 0 §6 almost field-for-field so the payload contract matches
the spec exactly.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.core.config import get_settings

settings = get_settings()


class SamplingMethod(str, Enum):
    STRATIFIED_RANDOM = "stratified_random"
    SIMPLE_RANDOM = "simple_random"


class AllocationMethod(str, Enum):
    PROPORTIONAL = "proportional"
    EQUAL = "equal"
    AUTOMATIC = "automatic"


class SamplingParameters(BaseModel):
    samples_per_class: str | int = "automatic"
    random_seed: int = settings.random_seed
    minimum_per_class: int = settings.min_samples_per_class
    allocation_method: AllocationMethod = AllocationMethod.PROPORTIONAL


class SamplingOutputFormat(str, Enum):
    GEOJSON = "GeoJSON"
    CSV = "CSV"
    SHAPEFILE = "Shapefile"


class SamplingOutputOptions(BaseModel):
    include_geometry: bool = True
    include_class_label: bool = True
    include_pixel_values: bool = True
    coordinate_system: str = "EPSG:4326"
    formats: list[SamplingOutputFormat] = Field(
        default_factory=lambda: [
            SamplingOutputFormat.GEOJSON,
            SamplingOutputFormat.CSV,
            SamplingOutputFormat.SHAPEFILE,
        ]
    )


class SamplingConfig(BaseModel):
    """Doc 0 §14 defaults: stratified random, 5,000 samples, 70/30 split."""

    enabled: bool = True
    method: SamplingMethod = SamplingMethod.STRATIFIED_RANDOM
    default_sample_size: int = settings.default_sample_size
    minimum_samples: int = settings.min_samples
    maximum_samples: int = settings.max_samples
    parameters: SamplingParameters = Field(default_factory=SamplingParameters)
    output: SamplingOutputOptions = Field(default_factory=SamplingOutputOptions)


class SamplingRequest(BaseModel):
    project_id: str
    aoi_id: str
    stratification_layer: str = Field(
        ..., description="Asset/band to stratify by, e.g. land cover or risk class raster."
    )
    config: SamplingConfig = Field(default_factory=SamplingConfig)


class SamplingSplitSummary(BaseModel):
    total_samples: int
    train_samples: int
    test_samples: int
    train_split: float = settings.train_split
    per_class_counts: dict[str, int]
