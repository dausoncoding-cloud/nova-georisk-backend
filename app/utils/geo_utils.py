"""
Geospatial helpers that don't belong to any single service.

`compute_aoi_stats` implements Doc 0 step 3 "System Computes: Area (m²),
Hectares, km², Perimeter" — geodesic area/length so figures are correct
regardless of where on the globe the AOI sits (no naive planar
projection assumptions).
"""
from __future__ import annotations

from pyproj import Geod
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

_GEOD = Geod(ellps="WGS84")


def compute_aoi_stats(geojson_geometry: dict) -> dict[str, float]:
    """
    Compute area (m², ha, km²) and perimeter (m) for a GeoJSON
    Polygon/MultiPolygon using geodesic calculations on the WGS84
    ellipsoid, per Doc 0 step 3.
    """
    geom: BaseGeometry = shape(geojson_geometry)
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"AOI geometry must be Polygon or MultiPolygon, got {geom.geom_type}")

    area_m2, perimeter_m = _geodesic_area_and_perimeter(geom)

    return {
        "area_m2": abs(area_m2),
        "area_hectares": abs(area_m2) / 10_000.0,
        "area_km2": abs(area_m2) / 1_000_000.0,
        "perimeter_m": abs(perimeter_m),
    }


def _geodesic_area_and_perimeter(geom: BaseGeometry) -> tuple[float, float]:
    if geom.geom_type == "Polygon":
        return _polygon_area_and_perimeter(geom)

    total_area = 0.0
    total_perimeter = 0.0
    for poly in geom.geoms:
        area, perim = _polygon_area_and_perimeter(poly)
        total_area += area
        total_perimeter += perim
    return total_area, total_perimeter


def _polygon_area_and_perimeter(polygon) -> tuple[float, float]:
    exterior_area, exterior_perimeter = _GEOD.geometry_area_perimeter(polygon.exterior)
    area = abs(exterior_area)
    perimeter = exterior_perimeter
    for interior in polygon.interiors:
        hole_area, hole_perimeter = _GEOD.geometry_area_perimeter(interior)
        area -= abs(hole_area)
        perimeter += hole_perimeter
    return area, perimeter
