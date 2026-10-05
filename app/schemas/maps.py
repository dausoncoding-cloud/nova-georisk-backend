"""
Request/response schemas for the flood map product endpoints
(app/api/v1/endpoints/maps.py). Like the FIRRIS calculators, these are
synchronous — array-in, array-out — since they operate on
already-extracted sample values, not raw rasters (raster/GeoTIFF
generation is a separate concern, app/services/maps/export.py, not
exposed over HTTP here since it needs a real filesystem path).
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


def _same_length_validator(other_field: str):
    def _validate(cls, value, info):
        other = info.data.get(other_field)
        if other is not None and len(other) != len(value):
            raise ValueError(f"{other_field} and this field must be the same length.")
        return value

    return _validate


class ClassifiedValuesResponse(BaseModel):
    values: list[float]
    labels: list[str]
    colors: list[str]


class FloodExtentRequest(BaseModel):
    backscatter_before: list[float]
    backscatter_during: list[float]
    change_ratio_threshold: float = 1.5

    _validate_length = field_validator("backscatter_during")(_same_length_validator("backscatter_before"))


class FloodExtentResponse(BaseModel):
    flooded: list[bool]


class FloodDepthRequest(BaseModel):
    water_surface_elevation: list[float]
    ground_elevation: list[float]

    _validate_length = field_validator("ground_elevation")(_same_length_validator("water_surface_elevation"))


class FloodVelocityRequest(BaseModel):
    discharge: list[float]
    cross_sectional_area: list[float]

    _validate_length = field_validator("cross_sectional_area")(_same_length_validator("discharge"))


class FloodHazardMapRequest(BaseModel):
    depth: list[float]
    velocity: list[float]

    _validate_length = field_validator("velocity")(_same_length_validator("depth"))


class ProbabilityRequest(BaseModel):
    probability: list[float]

    @field_validator("probability")
    @classmethod
    def _in_range(cls, value: list[float]) -> list[float]:
        if any(not (0.0 <= v <= 1.0) for v in value):
            raise ValueError("Every probability must be in [0, 1].")
        return value


class ReturnPeriodFromProbabilityRequest(BaseModel):
    annual_probability: list[float]

    @field_validator("annual_probability")
    @classmethod
    def _positive(cls, value: list[float]) -> list[float]:
        if any(v <= 0 for v in value):
            raise ValueError("Every annual_probability must be > 0.")
        return value


class DurationRequest(BaseModel):
    duration_days: list[float]


class ExposureDensityRequest(BaseModel):
    normalized_density: list[float]

    @field_validator("normalized_density")
    @classmethod
    def _in_range(cls, value: list[float]) -> list[float]:
        if any(not (0.0 <= v <= 1.0) for v in value):
            raise ValueError("Every value must be in [0, 1].")
        return value


class VulnerabilityMapRequest(BaseModel):
    fvi: list[float]

    @field_validator("fvi")
    @classmethod
    def _in_range(cls, value: list[float]) -> list[float]:
        if any(not (0.0 <= v <= 1.0) for v in value):
            raise ValueError("Every fvi value must be in [0, 1].")
        return value


class RiskMapRequest(BaseModel):
    hazard: list[float]
    exposure: list[float]
    vulnerability: list[float]

    @field_validator("exposure")
    @classmethod
    def _len_matches_hazard(cls, value, info):
        hazard = info.data.get("hazard")
        if hazard is not None and len(hazard) != len(value):
            raise ValueError("hazard and exposure must be the same length.")
        return value

    @field_validator("vulnerability")
    @classmethod
    def _len_matches_all(cls, value, info):
        hazard = info.data.get("hazard")
        if hazard is not None and len(hazard) != len(value):
            raise ValueError("hazard, exposure, and vulnerability must all be the same length.")
        return value


class SusceptibilityRequest(BaseModel):
    susceptibility: list[float]

    @field_validator("susceptibility")
    @classmethod
    def _in_range(cls, value: list[float]) -> list[float]:
        if any(not (0.0 <= v <= 1.0) for v in value):
            raise ValueError("Every value must be in [0, 1].")
        return value


class ZonationRequest(BaseModel):
    zonation_score: list[float]

    @field_validator("zonation_score")
    @classmethod
    def _in_range(cls, value: list[float]) -> list[float]:
        if any(not (0.0 <= v <= 1.0) for v in value):
            raise ValueError("Every value must be in [0, 1].")
        return value
