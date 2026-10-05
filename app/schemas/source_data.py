"""Fail-closed source-data manifests. These attest metadata, not scientific truth."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.services.source_data.catalogue import get_profile


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class TemporalCoverage(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def check_range(self):
        if not self.start.tzinfo or not self.end.tzinfo or self.end < self.start:
            raise ValueError("Temporal coverage requires timezone-aware ordered timestamps")
        return self


class SpatialResolution(StrictModel):
    x: float = Field(gt=0)
    y: float = Field(gt=0)
    unit: Literal["m", "degree"]


class GeographicCoverage(StrictModel):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def check_bounds(self):
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("Geographic coverage is not ordered")
        return self


class QualityAssessment(StrictModel):
    method: str = Field(min_length=3)
    assessed_at: datetime
    assessor: str = Field(min_length=2)
    status: Literal["passed"]

    @model_validator(mode="after")
    def check_timestamp(self):
        if not self.assessed_at.tzinfo:
            raise ValueError("QA timestamp must be timezone-aware")
        return self


class Licence(StrictModel):
    identifier: str = Field(min_length=2)
    permitted_use: str = Field(min_length=3)
    redistribution: Literal["allowed", "restricted"]


class Provenance(StrictModel):
    producer: str = Field(min_length=2)
    custodian: str = Field(min_length=2)
    source_uri: str = Field(min_length=3)
    acquisition_method: str = Field(min_length=3)


class Uncertainty(StrictModel):
    measure: str = Field(min_length=2)
    value: float = Field(ge=0)
    unit: str = Field(min_length=1)
    confidence_level: float | None = Field(default=None, gt=0, le=1)


class SourceDatasetManifest(StrictModel):
    project_id: uuid.UUID
    category: str
    source_id: str = Field(min_length=1, max_length=255)
    crs: str
    vertical_datum: str | None
    units: str
    temporal_coverage: TemporalCoverage
    geographic_coverage: GeographicCoverage
    spatial_resolution: SpatialResolution | None
    positional_uncertainty_m: float | None = Field(ge=0)
    spatial_unit_reference: str | None = None
    quality_assessment: QualityAssessment
    licence: Licence
    provenance: Provenance
    uncertainty: Uncertainty
    sha256: str
    nodata: float | None = None
    indicator_units: dict[str, str] | None = None
    indicator_directions: dict[str, Literal["benefit", "cost"]] | None = None
    indicator_scale_descriptions: dict[str, str] | None = None
    missing_value_policy: Literal["reject"] | None = None
    class_scheme: dict[str, str] | None = None
    land_cover_scheme: Literal["esa_worldcover", "modis_lc_type1"] | None = None
    observation_interval_hours: float | None = Field(default=None, gt=0)
    inventory_asset_types: list[str] | None = None
    hydraulic_model_run_id: str | None = None
    hydraulic_model_validation_reference: str | None = None
    observation_year: int | None = Field(default=None, ge=1900, le=2200)
    event_definition: str | None = None

    @model_validator(mode="after")
    def check_category_contract(self):
        profile = get_profile(self.category)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ValueError("sha256 must be a 64-digit hexadecimal checksum")
        if not re.fullmatch(r"EPSG:[1-9][0-9]*", self.crs):
            raise ValueError("crs must be an EPSG authority code")
        if profile["crs"] == "EPSG:4326" and self.crs != "EPSG:4326":
            raise ValueError("CSV/GeoJSON source CRS must be EPSG:4326")
        if profile["vertical_datum"] == "required" and not self.vertical_datum:
            raise ValueError("This category requires an explicit vertical datum")
        if profile["vertical_datum"] == "not_applicable" and self.vertical_datum is not None:
            raise ValueError("Vertical datum is not applicable to this category")
        if self.units != profile["unit"]:
            raise ValueError(f"units must be {profile['unit']}")
        if profile["format"] == "geotiff":
            if self.spatial_resolution is None or self.nodata is None:
                raise ValueError("Raster resolution and nodata are required")
            if self.positional_uncertainty_m is not None:
                raise ValueError("Raster positional uncertainty belongs in resolution/uncertainty metadata")
        elif self.spatial_resolution is not None or self.nodata is not None:
            raise ValueError("Raster resolution/nodata are not applicable to CSV/GeoJSON")
        if profile["format"] == "geojson" and self.positional_uncertainty_m is None:
            raise ValueError("GeoJSON positional uncertainty is required")
        if "longitude_latitude_columns" in profile["geometry"] and self.positional_uncertainty_m is None:
            raise ValueError("Station/survey point positional uncertainty is required")
        if "spatial_unit_id_join" in profile["geometry"] and not self.spatial_unit_reference:
            raise ValueError("Indicator survey requires a declared boundary source reference")
        if self.category == "land_cover" and not self.class_scheme:
            raise ValueError("Land-cover class scheme is required")
        if self.land_cover_scheme is not None and self.category != "land_cover":
            raise ValueError("Land-cover scoring scheme is only applicable to land cover")
        if self.observation_interval_hours is not None and self.category != "rainfall_stations":
            raise ValueError("Observation interval is only applicable to rainfall stations")
        if self.inventory_asset_types is not None and self.category not in {"buildings", "critical_infrastructure", "economic_assets"}:
            raise ValueError("Asset inventory types are only applicable to Exposure asset sources")
        if self.inventory_asset_types is not None and (not self.inventory_asset_types or any(not item.strip() for item in self.inventory_asset_types)):
            raise ValueError("Asset inventory types must be nonempty")
        if self.category == "hydraulic_model_velocity" and (
            not self.hydraulic_model_run_id or not self.hydraulic_model_validation_reference
        ):
            raise ValueError("Hydraulic-model velocity requires a reviewed model run and validation reference")
        if self.category != "hydraulic_model_velocity" and (
            self.hydraulic_model_run_id is not None or self.hydraulic_model_validation_reference is not None
        ):
            raise ValueError("Hydraulic-model metadata is only applicable to hydraulic-model velocity")
        if self.category == "annual_inundation_observation":
            if not self.observation_year or not self.event_definition or len(self.event_definition.strip()) < 10:
                raise ValueError("Annual exceedance observation requires a year and explicit event definition")
            start, end = self.temporal_coverage.start, self.temporal_coverage.end
            if (start.year != self.observation_year or end.year != self.observation_year
                    or start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0)
                    or (start.month, start.day, start.hour, start.minute, start.second) != (1, 1, 0, 0, 0)
                    or (end.month, end.day, end.hour, end.minute, end.second) != (12, 31, 23, 59, 59)):
                raise ValueError("Annual observation must attest complete January–December coverage for its year")
        elif self.observation_year is not None or self.event_definition is not None:
            raise ValueError("Annual event metadata is only applicable to annual inundation observations")
        indicators = profile.get("required_indicators")
        if indicators and (not self.indicator_units or set(self.indicator_units) != set(indicators)
                       or any(not unit.strip() for unit in self.indicator_units.values())):
            raise ValueError("All required indicator units must be declared")
        if self.category == "vulnerability_indicators" and (
            not self.indicator_directions or set(self.indicator_directions) != set(indicators)
        ):
            raise ValueError("Every vulnerability indicator requires an explicit reviewed benefit/cost direction")
        if self.category == "vulnerability_indicators" and (
            self.missing_value_policy != "reject"
            or not self.indicator_scale_descriptions
            or set(self.indicator_scale_descriptions) != set(indicators)
            or any(not description.strip() for description in self.indicator_scale_descriptions.values())
        ):
            raise ValueError("Vulnerability indicators require reject-on-missing and a declared measurement scale for each indicator")
        if self.category == "community_capacity_indicators" and (
            self.missing_value_policy != "reject"
            or not self.indicator_directions
            or set(self.indicator_directions) != set(indicators)
            or any(direction != "benefit" for direction in self.indicator_directions.values())
            or not self.indicator_scale_descriptions
            or set(self.indicator_scale_descriptions) != set(indicators)
            or any(not description.strip() for description in self.indicator_scale_descriptions.values())
        ):
            raise ValueError("Community capacities require reviewed benefit orientations, measurement scales and reject-on-missing")
        if self.category == "inundation_time_slice" and self.temporal_coverage.start != self.temporal_coverage.end:
            raise ValueError("Inundation time slice must have one exact observation timestamp")
        return self


class SourceDatasetValidation(StrictModel):
    category: str
    format: str
    record_count: int
    bounds: list[float] | None
    sha256: str
    structural_validation_only: Literal[True] = True
    analysis_ready: Literal[False] = False


class SourceDatasetRegistered(SourceDatasetValidation):
    dataset_id: uuid.UUID


class SourceReadinessReview(StrictModel):
    evidence_refs: list[str] = Field(min_length=1)
    qa_verified: Literal[True]
    licence_verified: Literal[True]
    provenance_verified: Literal[True]
    crs_datum_verified: Literal[True]
    temporal_coverage_verified: Literal[True]
    uncertainty_reviewed: Literal[True]
    hydrologic_coverage_verified: bool = False
    dem_conditioning_verified: bool = False
    coverage_complete_verified: bool = False
    hydraulic_model_verified: bool = False
    annual_record_complete_verified: bool = False

    @model_validator(mode="after")
    def check_evidence(self):
        if any(not item.strip() for item in self.evidence_refs):
            raise ValueError("Readiness evidence references cannot be blank")
        return self


class SourceReadinessStatus(StrictModel):
    dataset_id: uuid.UUID
    analysis_ready: bool
    sha256: str
