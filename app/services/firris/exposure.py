"""Estimated exposure: people and buildings inside the observed extent and each return-period zone
(Depth & Exposure module, plan items 2.1–2.3).

* People: WorldPop R2025A for the event year, **area-weighted**: each 100 m cell × the fraction of its area inside the
  extent (sub-cell sampling). The "cells touching the extent" count is kept for transparency only (it overstates).
* Buildings: Open Buildings v3, centroid inside the extent, exact server-side counts at confidence ≥ 0.75 (≥ 0.65 as a
  sensitivity), tiling only on time-out, no sampling.
* Extents: the run's observed flood-candidate extent, reported unchanged as the flood map defines it (the map already
  excludes JRC permanent water, occurrence >= 90 %, at 30 m), and the GloFAS wet zone of each return period, from which
  GloFAS permanent water is excluded as in the hazard figures. The observed extent masked with the coarser GloFAS
  permanent water is kept in the record as a sensitivity note only (owner decision, 2026-11-17).
* Every figure is an estimate with its version, year, threshold and method; never "people affected".
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
from rasterio.features import rasterize, shapes
from rasterio.transform import Affine
from shapely.geometry import shape
from shapely.ops import unary_union

from app.services.firris.hazard_sources import GLOFAS_DATABASE_NOTICE, MIN_DEPTH_M, RETURN_PERIODS
from app.services.firris.modelled_hazard import cell_areas_km2
from app.services.gee.open_buildings import (OPEN_BUILDINGS_ASSET, OPEN_BUILDINGS_CITATION, OPEN_BUILDINGS_LICENCE,
                                             OPEN_BUILDINGS_VERSION, THRESHOLDS, BuildingCountUnavailable)
from app.services.gee.worldpop import (WORLDPOP_ASSET, WORLDPOP_CITATION, WORLDPOP_LICENCE, WORLDPOP_RELEASE,
                                       year_status)

logger = logging.getLogger(__name__)
WORLDPOP_ALPHA_CAVEAT = ("WorldPop R2025A is an alpha release: WorldPop states that it may change over the coming year as "
                         "improvements are made, so these population figures may change.")
BUILDINGS_LIMITATION = ("Open Buildings detection quality varies between areas; informal buildings and thatched or vegetated "
                        "roofs may be missed, so building counts may be too low.")
BUILDINGS_SPOT_CHECK = ("done 2026-11-17 by the owner on the Rufiji observed extent (Google Earth Pro, recent imagery, 5 views, "
                        "about 100 points): about 95% or more of the building points sit on real structures (metal, thatch and "
                        "mud roofs), a few on bare ground or under trees; some small buildings carry 2–3 points; omissions were "
                        "not assessed")
BUILT_UP_NOTE = ("Built-up areas can also produce SAR backscatter change unrelated to flooding (for example new or changed "
                 "buildings), which can add false flood candidates where people live.")
CLUSTER_BLOCK_CELLS = 6  # 6 × 3″ ≈ 550 m blocks for the "where are the exposed people" sentence
EXPOSURE_WORDING = ("Estimated exposure: modelled people and detected buildings inside each extent. Not people affected, "
                    "not damage; the version, year, threshold and method are part of every figure.")
MAP_EXTENTS = ("observed_extent", "rp100")


def sample_mask(mask: np.ndarray, transform: Affine, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Value of a boolean raster at points (False outside the raster)."""
    cols, rows = (~transform) * (xs, ys)
    cols, rows = np.floor(cols).astype(np.int64), np.floor(rows).astype(np.int64)
    height, width = mask.shape
    ok = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    out = np.zeros(xs.shape, dtype=bool)
    out[ok] = mask[rows[ok], cols[ok]]
    return out


def extent_fraction(transform: Affine, shape_: tuple[int, int], aoi_geometry: dict, *,
                    include: list[tuple[np.ndarray, Affine]] = (), exclude: list[tuple[np.ndarray, Affine]] = (),
                    subcells: int | None = None, chunk_rows: int = 64) -> np.ndarray:
    """Fraction of each target cell inside AOI ∩ all ``include`` masks ∖ any ``exclude`` mask (sub-cell sampling)."""
    height, width = shape_
    k = subcells or (10 if height * width <= 300_000 else 5)
    out = np.zeros(shape_, dtype=np.float64)
    for r0 in range(0, height, chunk_rows):
        r1 = min(height, r0 + chunk_rows)
        fine = transform * Affine.translation(0, r0) * Affine.scale(1 / k)
        rows_f, cols_f = (r1 - r0) * k, width * k
        inside = rasterize([(aoi_geometry, 1)], out_shape=(rows_f, cols_f), transform=fine, fill=0, dtype="uint8").astype(bool)
        if include or exclude:
            cc, rr = np.meshgrid(np.arange(cols_f) + 0.5, np.arange(rows_f) + 0.5)
            xs, ys = fine * (cc, rr)
            xs, ys = np.asarray(xs), np.asarray(ys)
            for mask, mask_transform in include:
                inside &= sample_mask(mask, mask_transform, xs, ys)
            for mask, mask_transform in exclude:
                inside &= ~sample_mask(mask, mask_transform, xs, ys)
        out[r0:r1] = inside.reshape(r1 - r0, k, width, k).mean(axis=(1, 3))
    return out


def extent_geometry(mask: np.ndarray, transform: Affine, aoi_geometry: dict):
    """The extent as one (multi)polygon in EPSG:4326, clipped to the AOI."""
    if not mask.any():
        from shapely.geometry import GeometryCollection
        return GeometryCollection()
    parts = [shape(geom) for geom, value in shapes(mask.astype("uint8"), mask=mask, transform=transform) if value == 1]
    return unary_union(parts).intersection(shape(aoi_geometry))


def _buildings(geometry, count: Callable) -> dict[str, Any]:
    try:
        return {"status": "counted", **count(geometry)}
    except BuildingCountUnavailable as exc:
        return {"status": "not_available", "reason": str(exc)}


def exposure_rows(population, aoi_geometry: dict, *, observed: dict | None, hazard_layers: dict | None,
                  count: Callable) -> tuple[list[dict], dict[str, Any]]:
    """One row per extent (whole area, observed extent, each RP zone) and the arrays for the GIS layers."""
    pop, pop_t = population.population, population.transform
    areas = cell_areas_km2(pop_t, pop.shape)
    permanent = []
    if hazard_layers:
        permanent = [(hazard_layers["permanent_water"], hazard_layers["transform"])]
    # (key, label, reported mask, alternative mask or None, grid transform). The alternative is the sensitivity:
    # the observed extent masked with GloFAS permanent water; for a GloFAS zone, the zone with permanent water kept.
    extents: list[tuple[str, str, np.ndarray | None, np.ndarray | None, Affine | None]] = [
        ("whole_area", "Whole area (reference)", None, None, None)]
    if observed is not None and observed.get("extent") is not None:
        obs, obs_t = observed["extent"], observed["transform"]
        masked = None
        if permanent:  # sensitivity only: the coarser GloFAS permanent water on the extent's own grid
            height, width = obs.shape
            cc, rr = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
            xs, ys = obs_t * (cc, rr)
            masked = obs & ~sample_mask(permanent[0][0], permanent[0][1], np.asarray(xs), np.asarray(ys))
        extents.append(("observed_extent", "Observed flood candidates (this run)", obs, masked, obs_t))
    if hazard_layers:
        for period in RETURN_PERIODS:
            depth = hazard_layers["depth"][period]
            wet_all = np.isfinite(depth) & (depth >= MIN_DEPTH_M) & ~hazard_layers["spurious"] & hazard_layers["inside"]
            wet = wet_all & ~hazard_layers["permanent_water"]
            extents.append((f"rp{period}", f"Modelled 1-in-{period}-year zone", wet, wet_all, hazard_layers["transform"]))

    def figures(mask, mask_t):
        fraction = extent_fraction(pop_t, pop.shape, aoi_geometry, include=[] if mask is None else [(mask, mask_t)])
        geometry = shape(aoi_geometry) if mask is None else extent_geometry(mask, mask_t, aoi_geometry)
        return fraction, geometry, {"area_km2": float((fraction * areas).sum()), "people": float((pop * fraction).sum()),
                                    "people_cells_touching": float(pop[fraction > 0].sum()),
                                    "buildings": _buildings(geometry, count)}

    rows, arrays = [], {}
    for key, label, mask, mask_all, mask_t in extents:
        fraction, geometry, values = figures(mask, mask_t)
        row = {"extent": key, "label": label, **values}
        if mask_all is not None and key == "observed_extent":
            row["sensitivity_glofas_permanent_water_masked"] = figures(mask_all, mask_t)[2]
        elif mask_all is not None:  # transparency, as in the hazard figures: the same zone with permanent water kept
            row["including_permanent_water"] = figures(mask_all, mask_t)[2]
        rows.append(row)
        if key in MAP_EXTENTS:
            arrays[key] = {"people": (pop * fraction).astype(np.float32), "inside": fraction > 0, "geometry": geometry}
    return rows, arrays


def exposure_record(population, rows: list[dict], *, points: dict | None = None, users_accuracy_flood_pct: float | None = None,
                    cluster: dict | None = None, accuracy_reason: str | None = None) -> dict[str, Any]:
    status_year = year_status(population.countries, population.year)
    return {
        "status": "assessed", "reason": None, "wording": EXPOSURE_WORDING,
        "population": {"asset": WORLDPOP_ASSET, "release": WORLDPOP_RELEASE, "year": population.year,
                       "requested_year": population.requested_year, "year_status": status_year,
                       "method": "area-weighted: people per 100 m cell × fraction of the cell inside the extent",
                       "source": population.provenance(), "citation": WORLDPOP_CITATION, "licence": WORLDPOP_LICENCE,
                       "release_caveat": WORLDPOP_ALPHA_CAVEAT},
        "buildings": {"asset": OPEN_BUILDINGS_ASSET, "version": OPEN_BUILDINGS_VERSION, "primary_threshold": THRESHOLDS[0],
                      "sensitivity_threshold": THRESHOLDS[1],
                      "method": "centroid inside the extent; exact server-side count; tiles only after a time-out; no sampling",
                      "threshold_note": "No precision per confidence threshold is published; 0.75 is our stated choice.",
                      "limitation": BUILDINGS_LIMITATION, "spot_check": BUILDINGS_SPOT_CHECK,
                      "citation": OPEN_BUILDINGS_CITATION, "licence": OPEN_BUILDINGS_LICENCE},
        "permanent_water": ("The observed flood candidates are reported as the flood map defines them (JRC permanent water, "
                            "occurrence >= 90 %, already excluded at 30 m). GloFAS permanent-water cells are excluded from the "
                            "modelled return-period zones only, as in the hazard figures."),
        "rows": rows,
        "observed_extent_caveat": observed_extent_caveat(users_accuracy_flood_pct, accuracy_reason) if any(
            r["extent"] == "observed_extent" for r in rows) else None,
        "observed_cluster": cluster,
        "glofas_zone_notice": ("The return-period zones come from the GloFAS flood hazard maps: " + GLOFAS_DATABASE_NOTICE),
        "building_points": {k: v for k, v in (points or {}).items() if k != "features"} or None,
    }


def observed_extent_caveat(users_accuracy_flood_pct: float | None, reason: str | None = None) -> dict[str, Any]:
    """The observed extent inherits the flood map's commission error (owner, 2026-11-17).

    ``reason`` (for example "The Sentinel-2 reference covers only 0.42% of the area …") replaces the default
    "no independent Sentinel-2 comparison" when the comparison exists but is not representative.
    """
    if users_accuracy_flood_pct is None:
        why = (reason[0].lower() + reason[1:]).rstrip(".") if reason else "no independent Sentinel-2 comparison"
        short = why.split(" (")[0]
        text = (f"These figures inherit the flood map's commission error, which is not assessable for this run ({short}), "
                "so some of these people and buildings may lie outside the real flood.")
        return {"status": "not_assessable", "users_accuracy_flood_pct": None, "text": text, "built_up_note": BUILT_UP_NOTE,
                "reason_short": short if reason else None}
    text = (f"These figures inherit the flood map's commission error: against the independent Sentinel-2 reference, "
            f"{users_accuracy_flood_pct:.1f}% of the pixels mapped as flood candidates were flooded (user's accuracy for flood), "
            "so part of these people and buildings may lie outside the real flood.")
    return {"status": "assessed", "users_accuracy_flood_pct": float(users_accuracy_flood_pct), "text": text,
            "built_up_note": BUILT_UP_NOTE}


def observed_cluster(people: np.ndarray, transform: Affine, *, block: int = CLUSTER_BLOCK_CELLS) -> dict[str, Any] | None:
    """Where most observed-extent people are: the smallest set of ~550 m blocks holding half of them, if compact."""
    total = float(people.sum())
    if total <= 0:
        return None
    height, width = people.shape
    rows, cols = -(-height // block), -(-width // block)
    padded = np.zeros((rows * block, cols * block))
    padded[:height, :width] = people
    sums = padded.reshape(rows, block, cols, block).sum(axis=(1, 3)).ravel()
    order = np.argsort(sums)[::-1]
    chosen, held = [], 0.0
    for index in order:
        chosen.append(index)
        held += sums[index]
        if held >= 0.5 * total:
            break
    r, c = np.unravel_index(chosen, (rows, cols))
    west, north = transform * (int(c.min()) * block, int(r.min()) * block)
    east, south = transform * ((int(c.max()) + 1) * block, (int(r.max()) + 1) * block)
    compact = (east - west) <= 0.05 and (north - south) <= 0.05  # about 5.5 km
    share = held / total * 100
    def lon(v):
        return f"{abs(v):.3f}°{'E' if v >= 0 else 'W'}"
    def lat(v):
        return f"{abs(v):.3f}°{'N' if v >= 0 else 'S'}"
    lats = sorted((south, north), key=abs)
    place = f"{lon(west)[:-2]}–{lon(east)}, {lat(lats[0])[:-2]}–{lat(lats[1])}"
    text = (f"About half of these people ({share:.0f}%) are in a settled area around {place}, where SAR change can be "
            "unrelated to flooding." if compact else None)
    return {"share_pct": share, "blocks": len(chosen), "bounds": {"west": west, "south": south, "east": east, "north": north},
            "place": place, "compact": compact, "text": text}


def cluster_glofas_check(cluster: dict | None, hazard_layers: dict | None, period: int = 500) -> dict[str, Any] | None:
    """How much of the settled cluster GloFAS models as wet at the longest return period (context for the report)."""
    if not cluster or not cluster.get("compact") or not hazard_layers:
        return None
    t = hazard_layers["transform"]
    height, width = hazard_layers["permanent_water"].shape
    cc, rr = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
    xs, ys = t * (cc, rr)
    b = cluster["bounds"]
    inside = ((np.asarray(xs) >= b["west"]) & (np.asarray(xs) <= b["east"]) & (np.asarray(ys) >= b["south"])
              & (np.asarray(ys) <= b["north"]) & hazard_layers["inside"])
    cells = int(inside.sum())
    if not cells:
        return None
    depth = hazard_layers["depth"][period]
    wet = np.isfinite(depth) & (depth >= MIN_DEPTH_M) & ~hazard_layers["permanent_water"] & ~hazard_layers["spurious"]
    return {"return_period_years": period, "cells": cells, "wet_pct": float((wet & inside).sum() / cells * 100),
            "permanent_water_pct": float((hazard_layers["permanent_water"] & inside).sum() / cells * 100)}


def unavailable_exposure(reason: str) -> dict[str, Any]:
    return {"status": "not_available", "reason": reason, "wording": EXPOSURE_WORDING, "rows": []}


def run_exposure(aoi_geometry: dict, *, event_year: int | None, extent: np.ndarray | None, extent_transform: Affine | None,
                 extent_crs: str, hazard_layers: dict | None, acquire=None, count=None, points=None,
                 users_accuracy_flood_pct: float | None = None,
                 accuracy_reason: str | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Population and buildings for every extent; on failure, a 'not available' record (the flood map is unaffected)."""
    from app.services.gee.open_buildings import building_points, count_buildings
    from app.services.gee.worldpop import PopulationUnavailable, acquire_worldpop

    acquire, count, points = acquire or acquire_worldpop, count or count_buildings, points or building_points
    if event_year is None:
        return unavailable_exposure("The target period of the run is not recorded, so the population year cannot be chosen."), None
    if extent_crs and extent_crs.upper() not in ("EPSG:4326", "OGC:CRS84"):
        return unavailable_exposure(f"Exposure needs the analysis grid in EPSG:4326 (this run: {extent_crs})."), None
    try:
        population = acquire(aoi_geometry, event_year)
    except PopulationUnavailable as exc:
        return unavailable_exposure(str(exc)), None
    except Exception:  # noqa: BLE001 - any provider failure leaves the flood map intact
        logger.exception("WorldPop could not be read")
        return unavailable_exposure("WorldPop could not be read from Earth Engine for this run. The flood map is unaffected; "
                                    "run the analysis again to add the exposure estimate."), None
    observed = {"extent": extent, "transform": extent_transform} if extent is not None and extent_transform is not None else None
    rows, arrays = exposure_rows(population, aoi_geometry, observed=observed, hazard_layers=hazard_layers, count=count)
    building_layer = None
    if "observed_extent" in arrays:
        try:
            building_layer = points(arrays["observed_extent"]["geometry"])
        except Exception as exc:  # noqa: BLE001 - the layer is optional; counts stay exact
            building_layer = {"status": "not_delivered", "reason": f"The building layer could not be read: {exc}", "features": []}
    cluster = observed_cluster(arrays["observed_extent"]["people"], population.transform) if "observed_extent" in arrays else None
    if cluster is not None:
        cluster["glofas"] = cluster_glofas_check(cluster, hazard_layers)
    record = exposure_record(population, rows, points=building_layer, users_accuracy_flood_pct=users_accuracy_flood_pct,
                             cluster=cluster, accuracy_reason=accuracy_reason)
    layers = {"population_transform": population.transform, "arrays": arrays, "building_points": building_layer}
    return record, layers
