"""Modelled flood hazard statistics (Depth & Exposure module, plan items 1.2 and 1.4).

Inputs are GloFAS v2.1 depth rasters on their native grid (``glofas_hazard.acquire_glofas``). Every statistic is
area-weighted: weight = (fraction of the cell inside the AOI) × (cell area on the WGS84 ellipsoid).

* A cell is wet for a return period when its depth is >= 0.1 m (the dataset minimum).
* Permanent water is not flooding: cells flagged ``permanent_water_class`` are excluded from the hazard figures and
  reported separately (the GloFAS maps carry a depth there because permanent water was used to patch them).
* Cells flagged ``spurious_depth_category`` (depths > 10 m in small channels) are excluded and reported.
* AEP = 1 / T (Gumbel fit to annual maximum discharge, plan §2a.2); P(at least once in n years) = 1 − (1 − 1/T)^n.
No value is tuned; nothing here changes the flood-extent science (firris-science-2).
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from pyproj import Geod
from rasterio.features import rasterize
from rasterio.transform import Affine

from app.services.firris.hazard_sources import (DEPTH_BINS, GLOFAS_ATTRIBUTION, GLOFAS_CATEGORY_CODES, GLOFAS_CITATION,
                                                GLOFAS_LICENCE, GLOFAS_LICENCE_CONFIRMED, GLOFAS_METHOD_NOTE,
                                                GLOFAS_METHOD_REFERENCES, METHOD_VERSION, MIN_DEPTH_M, OCCURRENCE_YEARS,
                                                RETURN_PERIODS)

SUPERSAMPLE = 10  # sub-cells per side for the AOI fraction of edge cells
_GEOD = Geod(ellps="WGS84")


# --- probabilities ----------------------------------------------------------------------------------------------

def aep(return_period: float) -> float:
    """Annual exceedance probability of the T-year flow (annual maxima): 1 / T."""
    if not return_period or return_period <= 1:
        raise ValueError("A return period must be greater than 1 year")
    return 1.0 / float(return_period)


def probability_at_least_once(return_period: float, years: int) -> float:
    """P(at least one exceedance in n years) = 1 − (1 − 1/T)^n, assuming independent years."""
    if years < 1:
        raise ValueError("The number of years must be at least 1")
    return 1.0 - (1.0 - aep(return_period)) ** int(years)


def occurrence_table(return_periods: Iterable[int] = RETURN_PERIODS, years: Iterable[int] = OCCURRENCE_YEARS) -> list[dict]:
    years = list(years)
    return [{"return_period_years": int(t), "aep": aep(t),
             "probability_at_least_once": {str(n): probability_at_least_once(t, n) for n in years}}
            for t in return_periods]


# --- grid helpers -----------------------------------------------------------------------------------------------

def cell_fractions(aoi_geometry: dict, transform: Affine, shape: tuple[int, int], *, supersample: int = SUPERSAMPLE) -> np.ndarray:
    """Fraction (0–1) of each cell inside the AOI polygon, from a supersampled cell-centre mask."""
    height, width = shape
    fine = transform * Affine.scale(1 / supersample)
    inside = rasterize([(aoi_geometry, 1)], out_shape=(height * supersample, width * supersample), transform=fine,
                       fill=0, all_touched=False, dtype="uint8")
    return inside.reshape(height, supersample, width, supersample).mean(axis=(1, 3)).astype(np.float64)


def cell_areas_km2(transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """Area of each cell of a north-up longitude/latitude grid on the WGS84 ellipsoid (km²)."""
    height, width = shape
    areas = np.empty(height, dtype=np.float64)
    for row in range(height):
        west, north = transform * (0, row)
        east, south = transform * (1, row + 1)
        area, _ = _GEOD.polygon_area_perimeter([west, east, east, west], [south, south, north, north])
        areas[row] = abs(area) / 1e6
    return np.repeat(areas[:, None], width, axis=1)


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float | None:
    """Lower weighted quantile: the smallest value whose cumulative weight reaches q of the total."""
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    keep = weights > 0
    if not keep.any():
        return None
    order = np.argsort(values[keep], kind="stable")
    v, w = values[keep][order], weights[keep][order]
    cumulative = np.cumsum(w)
    return float(v[np.searchsorted(cumulative, q * cumulative[-1], side="left")])


# --- statistics -------------------------------------------------------------------------------------------------

def _bin_label(low: float, high: float | None) -> str:
    return f"> {low:g} m" if high is None else f"{low:g}–{high:g} m"


def depth_statistics(depth: np.ndarray, weights: np.ndarray, aoi_area_km2: float) -> dict[str, Any]:
    wet = np.isfinite(depth) & (depth >= MIN_DEPTH_M) & (weights > 0)
    area = float(weights[wet].sum())
    values, w = depth[wet].astype(float), weights[wet]
    classes = []
    for low, high in DEPTH_BINS:
        in_bin = (values >= low) & ((values < high) if high is not None else True)
        part = float(w[in_bin].sum())
        classes.append({"label": _bin_label(low, high), "min_m": low, "max_m": high, "area_km2": part,
                        "pct_of_wet": part / area * 100 if area else None})
    return {"wet_area_km2": area, "wet_pct_of_aoi": area / aoi_area_km2 * 100 if aoi_area_km2 else None,
            "wet_cells": int(wet.sum()),
            "depth_m": {"p50": weighted_quantile(values, w, 0.5), "mean": float(np.average(values, weights=w)) if area else None,
                        "p90": weighted_quantile(values, w, 0.9), "max": float(values.max()) if values.size else None},
            "classes": classes}


def observed_inside(extent: np.ndarray, extent_transform: Affine, extent_crs: str, hazard_transform: Affine,
                    hazard_wet: np.ndarray, permanent_water: np.ndarray) -> dict[str, float | None]:
    """Share of the observed flood-candidate pixels whose centres fall in the RP wet zone (context, not accuracy)."""
    rows, cols = np.nonzero(extent)
    if rows.size == 0:
        return {"inside_pct": None, "in_permanent_water_pct": None, "pixels": 0}
    xs, ys = extent_transform * (cols + 0.5, rows + 0.5)
    xs, ys = np.asarray(xs), np.asarray(ys)
    if extent_crs and extent_crs.upper() not in ("EPSG:4326", "OGC:CRS84"):
        from pyproj import Transformer
        xs, ys = Transformer.from_crs(extent_crs, "EPSG:4326", always_xy=True).transform(xs, ys)
    inverse = ~hazard_transform
    hc, hr = inverse * (xs, ys)
    hc, hr = np.floor(hc).astype(int), np.floor(hr).astype(int)
    height, width = hazard_wet.shape
    ok = (hr >= 0) & (hr < height) & (hc >= 0) & (hc < width)
    inside = np.zeros(rows.size, dtype=bool)
    in_pw = np.zeros(rows.size, dtype=bool)
    inside[ok] = hazard_wet[hr[ok], hc[ok]]
    in_pw[ok] = permanent_water[hr[ok], hc[ok]]
    return {"inside_pct": float(inside.mean() * 100), "in_permanent_water_pct": float(in_pw.mean() * 100),
            "pixels": int(rows.size)}


def hazard_record(stack, aoi_geometry: dict, *, observed: dict | None = None) -> dict[str, Any]:
    """The result-summary record of the modelled hazard (statistics per return period, AEP table, provenance).

    ``observed`` optionally carries ``extent`` (bool array), ``transform`` and ``crs`` of the run's flood extent.
    """
    shape = stack.covered.shape
    fraction = cell_fractions(aoi_geometry, stack.transform, shape)
    areas = cell_areas_km2(stack.transform, shape)
    weights_all = fraction * areas
    aoi_area = float(weights_all.sum())
    covered_area = float(weights_all[stack.covered].sum())
    weights = np.where(stack.covered, weights_all, 0.0)
    hazard_weights = np.where(stack.permanent_water | stack.spurious, 0.0, weights)
    permanent_area = float(weights[stack.permanent_water].sum())
    spurious_area = float(weights[stack.spurious & ~stack.permanent_water].sum())
    periods = []
    for period in RETURN_PERIODS:
        depth = stack.depth[period]
        stats = depth_statistics(depth, hazard_weights, aoi_area)
        with_pw = depth_statistics(depth, np.where(stack.spurious, 0.0, weights), aoi_area)
        row = {"return_period_years": period, "aep": aep(period), **stats,
               "including_permanent_water": {"wet_area_km2": with_pw["wet_area_km2"], "wet_pct_of_aoi": with_pw["wet_pct_of_aoi"],
                                             "depth_m": with_pw["depth_m"]}}
        if observed is not None and observed.get("extent") is not None:
            wet = np.isfinite(depth) & (depth >= MIN_DEPTH_M) & ~stack.permanent_water & ~stack.spurious
            row["observed_extent"] = observed_inside(observed["extent"], observed["transform"], observed.get("crs", "EPSG:4326"),
                                                     stack.transform, wet, stack.permanent_water)
        periods.append(row)
    status = "assessed" if any(p["wet_area_km2"] > 0 for p in periods) else "no_modelled_flooding"
    return {
        "status": status,
        "reason": None if status == "assessed" else
        "No GloFAS flood depth at any return period inside the area (outside the modelled river floodplains).",
        "method_version": METHOD_VERSION,
        "aoi": {"area_km2": aoi_area, "covered_km2": covered_area,
                "covered_pct": covered_area / aoi_area * 100 if aoi_area else None},
        "permanent_water_km2": permanent_area, "permanent_water_pct_of_aoi": permanent_area / aoi_area * 100 if aoi_area else None,
        "spurious_km2": spurious_area,
        "return_periods": periods,
        "occurrence": {"years": list(OCCURRENCE_YEARS), "rows": occurrence_table()},
        "method": {"wet_rule": f"depth >= {MIN_DEPTH_M} m", "weights": "cell fraction inside the AOI × WGS84 cell area",
                   "permanent_water": "excluded from the hazard figures; reported separately",
                   "spurious_depth": "excluded and reported", "depth_bins_m": [list(b) for b in DEPTH_BINS],
                   "aep": "AEP = 1/T (Gumbel fit to annual maximum discharge)",
                   "probability_at_least_once": "1 − (1 − 1/T)^n, independent years", "note": GLOFAS_METHOD_NOTE,
                   "category_codes_recorded_not_shown": dict(GLOFAS_CATEGORY_CODES)},
        "source": stack.provenance(),
        "citation": GLOFAS_CITATION, "method_references": list(GLOFAS_METHOD_REFERENCES),
        "attribution": GLOFAS_ATTRIBUTION, "licence": GLOFAS_LICENCE, "licence_confirmed": GLOFAS_LICENCE_CONFIRMED,
    }


def unavailable_record(reason: str) -> dict[str, Any]:
    return {"status": "not_available", "reason": reason, "method_version": METHOD_VERSION, "return_periods": [],
            "occurrence": {"years": list(OCCURRENCE_YEARS), "rows": occurrence_table()},
            "citation": GLOFAS_CITATION, "attribution": GLOFAS_ATTRIBUTION, "licence": GLOFAS_LICENCE,
            "licence_confirmed": GLOFAS_LICENCE_CONFIRMED}
