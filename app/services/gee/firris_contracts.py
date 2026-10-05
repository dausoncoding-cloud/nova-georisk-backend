"""Executable FIRRIS acquisition policies; no dataset substitutions or pixel filling."""
from datetime import date
import math

import numpy as np
from pyproj import CRS
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from shapely.geometry import shape

INDEX_BANDS = {
    "ndvi": ("B8", "B4"), "mndwi": ("B3", "B11"),
    "ndbi": ("B11", "B8"), "ndwi": ("B3", "B8"), "ndmi": ("B8", "B11"),
}
CORRECTIONS = {
    "COPERNICUS/S2_SR_HARMONIZED": {
        "surface_reflectance": "provider Level-2A; harmonized DN",
        "additional_atmospheric_correction": "not applied",
        "additional_terrain_correction": "not applied; no reviewed optical terrain policy",
        "reflectance_scale": 0.0001,
        "reference": "https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED",
    },
    "COPERNICUS/S1_GRD": {
        "surface_reflectance": "not applicable; SAR backscatter in dB",
        "radiometric_calibration": "provider applied",
        "geometric_terrain_correction": "provider applied",
        "additional_radiometric_terrain_flattening": "not applied; no reviewed policy",
        "reference": "https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD",
    },
}


def periods(config):
    result = {}
    for key in ("target_period", "baseline_period"):
        try:
            start = date.fromisoformat(str(config[key]["start"]))
            end = date.fromisoformat(str(config[key]["end"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("FIRRIS requires ISO target and baseline periods") from exc
        if start >= end:
            raise ValueError("FIRRIS date ranges must be ordered, end-exclusive")
        result[key] = {"start": start.isoformat(), "end": end.isoformat()}
    if result["baseline_period"]["end"] > result["target_period"]["start"]:
        raise ValueError("Baseline must precede target without overlap")
    target_start = date.fromisoformat(result["target_period"]["start"])
    target_end = date.fromisoformat(result["target_period"]["end"])
    baseline_start = date.fromisoformat(result["baseline_period"]["start"])
    baseline_end = date.fromisoformat(result["baseline_period"]["end"])
    annual = all((s.month, s.day, e.month, e.day, e.year - s.year) == (1, 1, 1, 1, 1)
                 for s, e in ((target_start, target_end), (baseline_start, baseline_end)))
    seasonal = ((target_start.month, target_start.day, target_end.month, target_end.day) ==
                (baseline_start.month, baseline_start.day, baseline_end.month, baseline_end.day))
    mode = config.get("date_mode", "pre-post")
    if mode not in {"annual", "seasonal", "pre-post"} or (mode == "annual" and not annual) or (mode == "seasonal" and not seasonal):
        raise ValueError("Unsupported dataset/date mode combination or invalid calendar windows")
    return result, mode


def validate_aoi(geometry):
    polygon = shape(geometry)
    if polygon.geom_type not in {"Polygon", "MultiPolygon"} or polygon.is_empty or not polygon.is_valid:
        raise ValueError("FIRRIS AOI must be a valid Polygon or MultiPolygon")
    west, south, east, north = polygon.bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("FIRRIS AOI must use WGS84 longitude/latitude")


def validate_grid(crs, transform, scale=None):
    parsed = CRS.from_user_input(crs)
    if not (parsed.is_geographic or parsed.is_projected):
        raise ValueError("Output CRS must be geographic or projected")
    if not all(math.isfinite(v) for v in transform[:6]) or transform.b or transform.d or transform.a <= 0 or transform.e >= 0:
        raise ValueError("FIRRIS requires a finite north-up nonrotated grid")
    if scale is not None and parsed.is_projected:
        factors = [axis.unit_conversion_factor for axis in parsed.axis_info[:2]]
        if len(factors) != 2 or not np.allclose([transform.a * factors[0], -transform.e * factors[1]], scale, rtol=1e-6):
            raise ValueError("Projected export resolution differs from requested scale in metres")
    return parsed


def assess_pixels(values, geometry, transform, crs, minimum):
    if not math.isfinite(minimum) or not 0 <= minimum <= 100:
        raise ValueError("Minimum valid coverage must be finite and between 0 and 100")
    validate_aoi(geometry)
    validate_grid(crs, transform)
    projected_geometry = transform_geom("EPSG:4326", crs, geometry)
    west, south, east, north = shape(projected_geometry).bounds
    height, width = values.shape[1:]
    left, top = transform * (0, 0)
    right, bottom = transform * (width, height)
    tolerance = max(abs(transform.a), abs(transform.e)) * 1e-6
    if west < left - tolerance or east > right + tolerance or south < bottom - tolerance or north > top + tolerance:
        raise ValueError("Export grid does not cover the complete AOI")
    aoi_mask = geometry_mask([projected_geometry],
                             out_shape=values.shape[1:], transform=transform, invert=True)
    if not aoi_mask.any():
        raise ValueError("Export grid does not intersect AOI")
    valid = aoi_mask & ~np.any(np.ma.getmaskarray(values), axis=0) & np.all(np.isfinite(values.filled(np.nan)), axis=0)
    labels = values[-1].filled(np.nan)
    if not np.isin(labels[valid], [0, 1]).all():
        raise ValueError("GEE screening labels must be binary")
    coverage = float(valid.sum() / aoi_mask.sum() * 100)
    if not valid.any() or coverage < minimum:
        raise ValueError(f"Valid pixel coverage {coverage:.2f}% is below the configured {minimum:.2f}% threshold")
    per_band = {str(i): int(np.count_nonzero(aoi_mask & (np.ma.getmaskarray(values)[i] | ~np.isfinite(values[i].filled(np.nan)))))
                for i in range(values.shape[0])}
    return valid, {"valid_pixel_coverage_pct": coverage, "aoi_cells": int(aoi_mask.sum()),
                   "valid_aoi_cells": int(valid.sum()), "missing_aoi_cells": int((aoi_mask & ~valid).sum()),
                   "missing_cells_by_band": per_band, "coverage_denominator": "AOI cell centers",
                   "gap_policy": "nodata preserved; no filling"}
