"""Typed contract for georeferenced screening-atlas thumbnails."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AtlasLegend(BaseModel):
    type: str
    minimum: float | None = None
    maximum: float | None = None
    palette: list[str] = Field(default_factory=list)
    entries: list[dict[str, Any]] = Field(default_factory=list)


class AtlasProduct(BaseModel):
    key: str
    label: str
    url: str
    filename: str
    bounds: list[float] = Field(min_length=4, max_length=4)
    crs: str | None
    width: int
    height: int
    units: str | None = None
    nodata: float | None = None
    legend: AtlasLegend | None = None


class AtlasManifestResponse(BaseModel):
    result_id: str | None
    version: int
    project_id: str
    aoi_id: str
    generated_at: str
    target_period: dict[str, str]
    baseline_period: dict[str, str]
    bounds: list[float] = Field(min_length=4, max_length=4)
    crs: str | None
    products: list[AtlasProduct]
    provenance: dict[str, Any]
    screening_caveat: str
    legacy: bool = False
