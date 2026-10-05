"""Reusable request validators."""
from __future__ import annotations

from shapely.geometry import shape
from shapely.validation import explain_validity


def validate_aoi_geometry(geojson_geometry: dict) -> None:
    """Raise ValueError with a human-readable reason if the AOI geometry is invalid."""
    geom = shape(geojson_geometry)
    if not geom.is_valid:
        raise ValueError(f"Invalid AOI geometry: {explain_validity(geom)}")
    if geom.is_empty:
        raise ValueError("AOI geometry is empty.")
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"AOI geometry must be Polygon or MultiPolygon, got {geom.geom_type}.")


def validate_date_range(start_date, end_date) -> None:
    if start_date >= end_date:
        raise ValueError("start_date must be earlier than end_date.")
