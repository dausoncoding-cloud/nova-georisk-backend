"""Open Buildings v3 counts inside an extent (Depth & Exposure module, plan item 2.2; Phase 0 §2a.6).

A building is counted when its centroid (the dataset's ``longitude_latitude``) lies inside the extent; its footprint
area is summed. Counts are exact and run server-side (no polygons are downloaded for counting). When one call exceeds
the time budget, the extent is split into 4 tiles (recursively, at most ``max_depth`` levels) and the tiles are run in
parallel; each centroid belongs to exactly one tile (half-open bounds: west/south edges inclusive). No sampling: if the
total budget is exceeded the count is reported as not available with the reason.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable

from shapely.geometry import box, mapping

OPEN_BUILDINGS_ASSET = "GOOGLE/Research/open-buildings/v3/polygons"
OPEN_BUILDINGS_VERSION = "v3 (inference May 2023)"
THRESHOLDS = (0.75, 0.65)  # primary, sensitivity
OPEN_BUILDINGS_CITATION = ("Sirko, W. et al. (2021). Continental-scale building detection from high resolution satellite "
                           "imagery. arXiv:2107.12283")
OPEN_BUILDINGS_LICENCE = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
CALL_BUDGET_S = 60
TOTAL_BUDGET_S = 600
MAX_DEPTH = 3
PARALLEL = 4
POINT_CAP = 20_000


class BuildingCountUnavailable(Exception):
    """The building count could not be completed within the budget (the reason is shown to the user)."""


def _server_count(geometry, bounds) -> dict[str, Any]:
    """One Earth Engine call: centroid-in-extent counts and footprint areas for both thresholds, inside ``bounds``."""
    import ee

    west, south, east, north = bounds
    extent = ee.Geometry(mapping(geometry))
    tile = ee.Geometry.Rectangle([west, south, east, north], None, False)
    candidates = ee.FeatureCollection(OPEN_BUILDINGS_ASSET).filterBounds(extent.intersection(tile, 1))
    points = candidates.filter(ee.Filter.gte("confidence", min(THRESHOLDS))).map(
        lambda f: ee.Feature(ee.Geometry(f.get("longitude_latitude")),
                             {"a": f.get("area_in_meters"), "c": f.get("confidence"),
                              "x": ee.Geometry(f.get("longitude_latitude")).coordinates().get(0),
                              "y": ee.Geometry(f.get("longitude_latitude")).coordinates().get(1)}))
    inside = (points.filter(ee.Filter.And(ee.Filter.gte("x", west), ee.Filter.lt("x", east),
                                          ee.Filter.gte("y", south), ee.Filter.lt("y", north)))
              .filterBounds(extent))
    result = {}
    for threshold in THRESHOLDS:
        selected = inside.filter(ee.Filter.gte("c", threshold))
        result[f"{threshold:.2f}"] = ee.Dictionary({"count": selected.size(), "area_m2": selected.aggregate_sum("a")})
    values = ee.Dictionary(result).getInfo()
    return {key: {"count": int(v["count"]), "area_m2": float(v["area_m2"] or 0.0)} for key, v in values.items()}


def _split(bounds) -> list[tuple[float, float, float, float]]:
    west, south, east, north = bounds
    mx, my = (west + east) / 2, (south + north) / 2
    return [(west, south, mx, my), (mx, south, east, my), (west, my, mx, north), (mx, my, east, north)]


def count_buildings(geometry, *, call: Callable | None = None, call_budget_s: float = CALL_BUDGET_S,
                    total_budget_s: float = TOTAL_BUDGET_S, max_depth: int = MAX_DEPTH, parallel: int = PARALLEL) -> dict[str, Any]:
    """Exact counts inside ``geometry`` (shapely, EPSG:4326), with adaptive tiling only when a call times out."""
    call = call or _server_count
    if geometry.is_empty:
        return {key: {"count": 0, "area_m2": 0.0} for key in (f"{t:.2f}" for t in THRESHOLDS)} | {
            "tiles": 0, "depth": 0, "seconds": 0.0, "method": "empty extent"}
    started = time.monotonic()
    west, south, east, north = geometry.bounds
    # A hair outside the bounds so that buildings on the east/north edge are inside the half-open root tile.
    pad = 1e-9
    pending = [((west, south, east + pad, north + pad), 0)]
    totals = {f"{t:.2f}": {"count": 0, "area_m2": 0.0} for t in THRESHOLDS}
    tiles = depth = 0
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while pending:
            if time.monotonic() - started > total_budget_s:
                raise BuildingCountUnavailable(
                    f"The building count did not finish within {total_budget_s:.0f} s for this area (dense buildings); "
                    "it is not reported. The population estimate is unaffected.")
            batch, pending = pending[:parallel], pending[parallel:]
            futures = []
            for bounds, level in batch:
                part = geometry.intersection(box(*bounds))
                if part.is_empty:
                    continue
                futures.append((bounds, level, pool.submit(call, part, bounds)))
            for bounds, level, future in futures:
                try:
                    values = future.result(timeout=call_budget_s)
                except (FutureTimeout, TimeoutError) as exc:
                    if level >= max_depth:
                        raise BuildingCountUnavailable(
                            "The building count timed out even after splitting the area into tiles; it is not reported. "
                            "The population estimate is unaffected.") from exc
                    pending.extend((child, level + 1) for child in _split(bounds))
                    continue
                except Exception as exc:  # noqa: BLE001 - Earth Engine "computation timed out" and similar
                    if "timed out" in str(exc).lower():
                        if level >= max_depth:
                            raise BuildingCountUnavailable(
                                "The building count timed out even after splitting the area into tiles; it is not reported. "
                                "The population estimate is unaffected.") from exc
                        pending.extend((child, level + 1) for child in _split(bounds))
                        continue
                    raise BuildingCountUnavailable(f"The building count could not be read from Earth Engine: {exc}") from exc
                tiles += 1
                depth = max(depth, level)
                for key, value in values.items():
                    totals[key]["count"] += value["count"]
                    totals[key]["area_m2"] += value["area_m2"]
    return {**totals, "tiles": tiles, "depth": depth, "seconds": round(time.monotonic() - started, 1),
            "method": "centroid inside the extent; exact server-side count" + (f"; {tiles} tiles" if tiles > 1 else "")}


def building_points(geometry, *, threshold: float = min(THRESHOLDS), cap: int = POINT_CAP) -> dict[str, Any]:
    """Centroids (with footprint area and confidence) inside the extent, for the GIS layer; capped, never sampled."""
    import ee

    extent = ee.Geometry(mapping(geometry))
    collection = (ee.FeatureCollection(OPEN_BUILDINGS_ASSET).filterBounds(extent)
                  .filter(ee.Filter.gte("confidence", threshold))
                  .map(lambda f: ee.Feature(ee.Geometry(f.get("longitude_latitude")),
                                            {"area_m2": f.get("area_in_meters"), "confidence": f.get("confidence"),
                                             "plus_code": f.get("full_plus_code")}))
                  .filterBounds(extent))
    size = collection.size().getInfo()
    if size > cap:
        return {"status": "not_delivered", "reason": f"{size:,} buildings exceed the layer cap of {cap:,}; counts are still exact.",
                "features": []}
    with_xy = collection.map(lambda f: f.set({"x": f.geometry().coordinates().get(0), "y": f.geometry().coordinates().get(1)}))
    columns = ee.Dictionary({key: with_xy.aggregate_array(key) for key in ("x", "y", "area_m2", "confidence", "plus_code")}).getInfo()
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]},
                 "properties": {"area_m2": area, "confidence": conf, "plus_code": code}}
                for x, y, area, conf, code in zip(columns["x"], columns["y"], columns["area_m2"], columns["confidence"],
                                                   columns["plus_code"])]
    return {"status": "delivered", "reason": None, "features": features}
