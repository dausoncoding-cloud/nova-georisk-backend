"""Area playground (P6): does an area fit one FRRIS analysis, and how to make it fit.

Uses exactly the preflight's capacity function (`preflight.capacity_estimate`, the calibrated Earth Engine request
size of the area's bounding box), so the playground and the analysis agree. Pure geometry: no provider calls.
Suggestions:
- trim: the largest box with the area's bounding-box proportions that fits, centred on a point (default the box
  centre; the browser moves it when the user drags), and the part of the area inside it;
- split: the fewest grid cells (up to MAX_PARTS) such that the part of the area in every cell fits on its own;
- coarser: 60 m if the whole area fits there, otherwise the preflight's suggested scale.
"""
from __future__ import annotations

from typing import Any

from shapely.geometry import box as make_box
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from app.services.firris.preflight import REQUEST_LIMIT_BYTES, capacity_estimate
from app.utils.geo_utils import compute_aoi_stats
from app.utils.validators import validate_aoi_geometry

NEAR_RATIO = 0.9
MAX_VERTICES = 20_000
MAX_PARTS = 16
COARSER_SCALE_M = 60.0
_MIN_PART_KM2 = 0.01  # slivers smaller than this are not offered as parts


def _vertices(geometry: dict) -> int:
    def count(value: Any) -> int:
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
            return 1
        return sum(count(item) for item in value) if isinstance(value, (list, tuple)) else 0
    return count(geometry.get("coordinates", []))


def _polygonal(geom: BaseGeometry) -> BaseGeometry | None:
    """Keep the polygonal part of an intersection (drops touching lines and points)."""
    if geom.is_empty:
        return None
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    polygons = [part for part in getattr(geom, "geoms", []) if part.geom_type in ("Polygon", "MultiPolygon")]
    if not polygons:
        return None
    from shapely.ops import unary_union
    merged = unary_union(polygons)
    return merged if merged.geom_type in ("Polygon", "MultiPolygon") else None


def _fits(bounds: tuple[float, float, float, float], scale: float) -> bool:
    return capacity_estimate(bounds, scale)["estimated_request_bytes"] <= REQUEST_LIMIT_BYTES


def _part(geom: BaseGeometry, scale: float) -> dict[str, Any]:
    geometry = mapping(geom)
    return {"geometry": geometry, "area_km2": compute_aoi_stats(geometry)["area_km2"], "bbox": list(geom.bounds),
            "capacity": capacity_estimate(geom.bounds, scale)}


def _trim(area: BaseGeometry, scale: float, center: list[float] | None) -> dict[str, Any] | None:
    west, south, east, north = area.bounds
    width, height = east - west, north - south
    low, high = 0.0, 1.0
    for _ in range(40):  # bisection on the share of the bounding box kept, same proportions
        mid = (low + high) / 2
        if _fits((0.0, 0.0, width * mid, height * mid), scale):
            low = mid
        else:
            high = mid
    if low <= 0:
        return None
    half_w, half_h = width * low / 2, height * low / 2
    cx, cy = center if center else ((west + east) / 2, (south + north) / 2)
    # Keep the box inside the area's bounding box.
    cx = min(max(cx, west + half_w), east - half_w)
    cy = min(max(cy, south + half_h), north - half_h)
    trimmed_box = (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    inside = _polygonal(area.intersection(make_box(*trimmed_box)))
    if inside is None:
        return None
    return {**_part(inside, scale), "box": list(trimmed_box)}


def _split(area: BaseGeometry, scale: float) -> dict[str, Any] | None:
    west, south, east, north = area.bounds
    width, height = east - west, north - south
    shapes = sorted(((rows, cols) for rows in range(1, MAX_PARTS + 1) for cols in range(1, MAX_PARTS + 1)
                     if 2 <= rows * cols <= MAX_PARTS),
                    key=lambda rc: (rc[0] * rc[1], abs((width / rc[1]) - (height / rc[0]))))
    for rows, cols in shapes:
        cell_w, cell_h = width / cols, height / rows
        if not _fits((0.0, 0.0, cell_w, cell_h), scale):
            continue  # even a full cell is too large: parts can only be smaller than their cell
        parts = []
        for row in range(rows):
            for col in range(cols):
                cell = make_box(west + col * cell_w, north - (row + 1) * cell_h, west + (col + 1) * cell_w, north - row * cell_h)
                inside = _polygonal(area.intersection(cell))
                if inside is not None and compute_aoi_stats(mapping(inside))["area_km2"] >= _MIN_PART_KM2:
                    parts.append(_part(inside, scale))
        if len(parts) >= 2 and all(part["capacity"]["estimated_request_bytes"] <= REQUEST_LIMIT_BYTES for part in parts):
            return {"rows": rows, "cols": cols, "parts": parts}
    return None


def _message(status: str, capacity: dict[str, Any]) -> str:
    if status == "fits":
        return "Fits comfortably in one analysis."
    if status == "near":
        return "Fits, but close to the limit. Small edits may push it over."
    times = capacity["ratio"]
    return (f"Too large for one analysis: about {times:.1f} times the 48 MiB limit. "
            "Choose a way to make it fit.")


def assess_area(geometry: dict, *, scale_m: float = 30.0, trim_center: list[float] | None = None) -> dict[str, Any]:
    """Raises ValueError (plain message) for geometry that cannot be an AOI."""
    if _vertices(geometry) > MAX_VERTICES:
        raise ValueError(f"The area has more than {MAX_VERTICES:,} vertices. Simplify it before checking.")
    validate_aoi_geometry(geometry)
    area = shape(geometry)
    west, south, east, north = area.bounds
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError("The area must be in longitude/latitude (EPSG:4326).")
    capacity = capacity_estimate(area.bounds, scale_m)
    ratio = capacity["estimated_request_bytes"] / REQUEST_LIMIT_BYTES
    status = "over" if ratio > 1 else "near" if ratio >= NEAR_RATIO else "fits"
    response: dict[str, Any] = {
        "status": status, "message": _message(status, capacity), "near_ratio": NEAR_RATIO,
        "area_km2": compute_aoi_stats(geometry)["area_km2"], "bbox": list(area.bounds),
        "bbox_km2": compute_aoi_stats(mapping(make_box(*area.bounds)))["area_km2"] if east > west and north > south else 0.0,
        "capacity": capacity, "trim": None, "split": None, "coarser": None,
    }
    if status == "over":
        response["trim"] = _trim(area, scale_m, trim_center)
        response["split"] = _split(area, scale_m)
        coarser = COARSER_SCALE_M if COARSER_SCALE_M > scale_m and _fits(area.bounds, COARSER_SCALE_M) else capacity["suggested_scale_m"]
        if coarser:
            response["coarser"] = {"scale_m": float(coarser), "capacity": capacity_estimate(area.bounds, coarser)}
    return response
