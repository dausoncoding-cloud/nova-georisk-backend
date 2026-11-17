"""Metadata-only FRRIS submission preflight (plan items 4.1, 4.4 and 4.6).

Checks, before any task exists and without downloading pixels:
- sensor date bounds: Sentinel-1 GRD starts on 2014-10-03; windows may not end after today (UTC);
- capacity: the synchronous Earth Engine download limit (48 MiB per request). Earth Engine counts
  exactly 93 bytes per output pixel for the current 12-band contract plus validity bands (calibrated
  2026-11-14, tests/unit/test_firris_preflight_capacity.py), and the pixel count below is an upper
  bound of its snapped output grid, so the estimate is never below the real request;
- Sentinel-1 availability: each window needs passes from exactly one relative orbit, the same in
  both windows (the rule enforced by the pipeline); empty windows report the nearest passes;
- Sentinel-2: per window, the scenes eligible for the independent reference, their tiles and the
  share of the AOI they cover, using the run's own eligibility and coverage function
  (scene_qa.optical_reference_qa). Warning only: without full cover the independent accuracy is not
  assessable, as in the run.

The same checks run in the preflight endpoint and again, server-side, when an analysis is submitted.
Provider errors and timeouts become one plain message; GEE internals are never returned.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import date, datetime, timedelta, timezone
from typing import Any

from shapely.geometry import shape

from app.services.reporting.dates import between_text, day_text
from app.schemas.analyses import (
    AnalysisPreflightCapacity,
    AnalysisPreflightIssue,
    AnalysisPreflightPeriod,
    AnalysisPreflightResponse,
    SatelliteSourceConfig,
)

logger = logging.getLogger(__name__)

SENTINEL1_START = date(2014, 10, 3)
SENTINEL2_SR_START = date(2017, 3, 28)
REQUEST_LIMIT_BYTES = 50_331_648  # Earth Engine getDownloadURL limit (staging §0.7)
BYTES_PER_PIXEL = 93  # Earth Engine's request cost per output pixel for the current band contract (calibrated)
METRES_PER_DEGREE = 111_319.49079327357  # Earth Engine's EPSG:4326 scale conversion
NEAREST_SEARCH_DAYS = 90
SUGGESTED_SCALES = (60, 90, 120, 150, 200, 250, 300, 500, 1000)
DEFAULT_TIMEOUT_SECONDS = 20.0
UNAVAILABLE_MESSAGE = ("Satellite availability could not be checked right now. Please try again in a minute; "
                       "no analysis was submitted.")

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="firris-preflight")


class PreflightUnavailable(Exception):
    """The provider could not be queried in time; carries only a plain message."""


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _issue(code: str, message: str, period: str | None = None) -> AnalysisPreflightIssue:
    return AnalysisPreflightIssue(code=code, message=message, period=period)


def _long(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def date_issues(windows: dict[str, tuple[date, date]], today: date) -> list[AnalysisPreflightIssue]:
    issues = []
    for name, (start, end) in windows.items():
        if start < SENTINEL1_START:
            issues.append(_issue("before_sentinel1_archive",
                                 f"Sentinel-1 data starts on {_long(SENTINEL1_START)}; the {name} window starts on "
                                 f"{start.isoformat()}. Choose dates on or after {SENTINEL1_START.isoformat()}.", name))
        if end > today + timedelta(days=1):
            issues.append(_issue("future_window",
                                 f"The {name} window ends after today ({today.isoformat()}, UTC). Satellite data for "
                                 "future dates does not exist yet.", name))
    return issues


def capacity_message(capacity: AnalysisPreflightCapacity) -> str:
    """Backlog §4.7 item 3: sizes in MiB (2^20 bytes), as computed."""
    mebibytes = capacity.estimated_request_bytes / 1_048_576
    advice = f", or a coarser resolution of {capacity.suggested_scale_m:g} m" if capacity.suggested_scale_m else ""
    return (f"This area needs about {mebibytes:,.0f} MiB per download at {capacity.scale_m:g} m, "
            f"{capacity.ratio:.1f} times the 48 MiB limit (about a 500 km² bounding box at 30 m). "
            f"Use a smaller area or split it into parts{advice}.")


def capacity_estimate(bounds: tuple[float, float, float, float], scale: float) -> dict[str, Any]:
    west, south, east, north = bounds
    step = scale / METRES_PER_DEGREE
    # Upper bound of Earth Engine's output grid (bbox snapped outward to the global pixel grid).
    pixels = (math.ceil((east - west) / step) + 1) * (math.ceil((north - south) / step) + 1)
    estimated = pixels * BYTES_PER_PIXEL
    suggested = None
    if estimated > REQUEST_LIMIT_BYTES:
        for candidate in SUGGESTED_SCALES:
            if candidate > scale and capacity_estimate(bounds, candidate)["estimated_request_bytes"] <= REQUEST_LIMIT_BYTES:
                suggested = float(candidate)
                break
    return {"scale_m": float(scale), "bbox_pixels": pixels, "estimated_request_bytes": estimated,
            "limit_bytes": REQUEST_LIMIT_BYTES, "ratio": round(estimated / REQUEST_LIMIT_BYTES, 3), "suggested_scale_m": suggested}


def scene_availability(aoi_geometry: dict, windows: dict[str, tuple[date, date]], max_cloud: float) -> dict[str, dict]:
    """Earth Engine metadata queries only (no pixels). Patched in tests."""
    from app.services.gee import auth, ingestion
    from app.services.gee.scene_qa import MAX_DEGRADED_MSI_PCT, aoi_coverage, footprint_polygon, granule_summary, optical_reference_qa
    ee = ingestion.ee
    auth.initialize_gee()
    aoi = ingestion.build_aoi_geometry(aoi_geometry)

    def to_date(millis):
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).date()

    periods: dict[str, dict] = {}
    for name, (start, end) in windows.items():
        s1 = ingestion.get_sentinel1_collection(aoi, start.isoformat(), end.isoformat())
        s2 = ingestion.get_sentinel2_collection(aoi, start.isoformat(), end.isoformat(), max_cloud_pct=max_cloud,
                                                max_degraded_msi_pct=MAX_DEGRADED_MSI_PCT)
        info = ee.Dictionary({"times": s1.aggregate_array("system:time_start"),
                              "orbits": s1.aggregate_array("relativeOrbitNumber_start"),
                              "footprints": s1.aggregate_array("system:footprint"), "s2": s2.size()}).getInfo()
        periods[name] = {"sentinel1_pass_dates": sorted({to_date(t) for t in info["times"]}),
                         "relative_orbits": sorted({int(o) for o in info["orbits"]}),
                         "sentinel2_compliant_scenes": int(info["s2"]),
                         "nearest_pass_before": None, "nearest_pass_after": None,
                         # r5.1: the run's own rule (scene_qa.aoi_coverage) on the same scenes' footprints.
                         SENTINEL1_COVERAGE_KEY: (aoi_coverage(aoi_geometry, [footprint_polygon(f) for f in info.get("footprints") or []])[1]
                                                  if info["times"] and info.get("footprints") else None)}
        if info["s2"]:
            try:
                record = optical_reference_qa(aoi, aoi_geometry, {"start": start.isoformat(), "end": end.isoformat()}, max_cloud)
            except ValueError:  # scenes exist but fail the run's per-scene QA: the reference is unusable
                logger.info("FRRIS preflight: Sentinel-2 %s window fails per-scene QA", name)
                periods[name]["sentinel2_aoi_coverage_pct"] = 0.0
            else:
                periods[name].update(sentinel2_compliant_scenes=record["scene_count"], sentinel2_tiles=record["tiles"],
                                     sentinel2_dates=[date.fromisoformat(d) for d in record["acquisition_dates"]],
                                     sentinel2_aoi_coverage_pct=record["aoi_coverage_pct"],
                                     sentinel2_summary=granule_summary(record))
    today = _today()
    for name, (start, end) in windows.items():
        if periods[name]["sentinel1_pass_dates"]:
            continue
        other = [o for key, value in periods.items() if key != name for o in value["relative_orbits"]]
        def search(lo: date, hi: date):
            collection = ingestion.get_sentinel1_collection(aoi, lo.isoformat(), hi.isoformat())
            if len(set(other)) == 1:  # a usable pass must share the other window's orbit
                collection = collection.filter(ee.Filter.eq("relativeOrbitNumber_start", other[0]))
            return collection
        lo = max(SENTINEL1_START, start - timedelta(days=NEAREST_SEARCH_DAYS))
        hi = min(today + timedelta(days=1), end + timedelta(days=NEAREST_SEARCH_DAYS))
        info = ee.Dictionary({"before": search(lo, start).aggregate_max("system:time_start") if lo < start else None,
                              "after": search(end, hi).aggregate_min("system:time_start") if end < hi else None}).getInfo()
        periods[name]["nearest_pass_before"] = to_date(info["before"]) if info.get("before") else None
        periods[name]["nearest_pass_after"] = to_date(info["after"]) if info.get("after") else None
    return periods


SENTINEL1_COVERAGE_KEY = "_sentinel1_aoi_coverage_pct"  # internal: not part of the API response


def coverage_issues(periods: dict[str, AnalysisPreflightPeriod], coverage: dict[str, float | None]) -> list[AnalysisPreflightIssue]:
    """r5.1: block when the radar passes of a window cover only part of the AOI, as the run would fail on it."""
    from app.services.gee.scene_qa import sentinel1_coverage_message
    issues = []
    for name, period in periods.items():
        covered = coverage.get(name)
        if period.sentinel1_pass_dates and covered is not None and covered < 100:
            issues.append(_issue("sentinel1_partial_coverage",
                                 sentinel1_coverage_message(period.start, period.end, covered, period.relative_orbits), name))
    return issues


def _orbit_issues(periods: dict[str, AnalysisPreflightPeriod]) -> list[AnalysisPreflightIssue]:
    issues = []
    for name, period in periods.items():
        if not period.sentinel1_pass_dates:
            # Backlog §4.7 item 22: the dates are the nearest passes themselves, not limits ("before 13 May").
            nearest = [f"{day_text(day)} ({label})" for label, day in (("before the window", period.nearest_pass_before),
                                                                       ("after the window", period.nearest_pass_after)) if day]
            if len(nearest) == 2:
                nearest[1] = nearest[1].replace("(after the window)", "(after)")
            hint = (f" Nearest usable pass{'es' if len(nearest) == 2 else ''}: {' and '.join(nearest)}." if nearest
                    else f" No usable pass within {NEAREST_SEARCH_DAYS} days either side.")
            issues.append(_issue("no_sentinel1_pass",
                                 f"No Sentinel-1 pass over this area {between_text(period.start, period.end)}.{hint}", name))
        elif len(period.relative_orbits) > 1:
            issues.append(_issue("multiple_orbits",
                                 f"The {name} window contains Sentinel-1 passes from relative orbits "
                                 f"{', '.join(map(str, period.relative_orbits))}. FRRIS needs passes from exactly one orbit, "
                                 "the same in both windows. Shorten the window to one pass date.", name))
    target, baseline = periods["target"], periods["baseline"]
    if not issues and target.relative_orbits != baseline.relative_orbits:
        issues.append(_issue("orbit_mismatch",
                             f"The target window uses Sentinel-1 relative orbit {target.relative_orbits[0]} and the baseline "
                             f"window uses orbit {baseline.relative_orbits[0]}. Both windows must use the same orbit; "
                             "choose a baseline date with a pass from the target's orbit."))
    return issues


def run_preflight(*, aoi_geometry: dict, source: SatelliteSourceConfig, today: date | None = None,
                  timeout: float | None = None) -> AnalysisPreflightResponse:
    today = today or _today()
    windows = {"target": (source.target_period.start, source.target_period.end),
               "baseline": (source.baseline_period.start, source.baseline_period.end)}
    blocking = date_issues(windows, today)
    capacity = AnalysisPreflightCapacity(**capacity_estimate(shape(aoi_geometry).bounds, source.scale))
    if capacity.estimated_request_bytes > capacity.limit_bytes:
        blocking.append(_issue("capacity_exceeded", capacity_message(capacity)))
    empty = {name: AnalysisPreflightPeriod(start=start, end=end) for name, (start, end) in windows.items()}
    if blocking:  # do not query the provider for a request that cannot run
        return AnalysisPreflightResponse(ok=False, capacity=capacity, blocking=blocking, **empty)
    future = _executor.submit(scene_availability, aoi_geometry, windows, source.max_cloud_pct)
    try:
        raw = future.result(timeout=timeout or DEFAULT_TIMEOUT_SECONDS)
    except FutureTimeout as exc:
        logger.warning("FRRIS preflight timed out")
        raise PreflightUnavailable(UNAVAILABLE_MESSAGE) from exc
    except Exception as exc:  # noqa: BLE001 - provider internals stay server-side
        logger.exception("FRRIS preflight provider query failed")
        raise PreflightUnavailable(UNAVAILABLE_MESSAGE) from exc
    coverage = {name: raw[name].pop(SENTINEL1_COVERAGE_KEY, None) for name in windows}
    periods = {name: AnalysisPreflightPeriod(start=windows[name][0], end=windows[name][1], **raw[name]) for name in windows}
    blocking = _orbit_issues(periods) + coverage_issues(periods, coverage)
    warnings = []
    for name, period in periods.items():
        coverage = period.sentinel2_aoi_coverage_pct
        if period.sentinel2_compliant_scenes and coverage is not None and coverage < 100:
            found = period.sentinel2_summary
            if found and period.sentinel2_tiles:
                found = found[:-1] + ": " + ", ".join(period.sentinel2_tiles) + ")"
            detail = (f"cover only {coverage:g}% of the area: {found}" if found
                      else "do not pass the quality checks used by the analysis")
            warnings.append(_issue("sentinel2_partial_coverage",
                                   f"The compliant Sentinel-2 scenes in the {name} window {detail}. The analysis can run, "
                                   "but its independent accuracy will not be assessable: the reference must cover the whole "
                                   "area. Widen the window to include a clear date over every tile, or continue.", name))
        if period.sentinel2_compliant_scenes == 0:
            reason = (f" Sentinel-2 surface reflectance is only available from {SENTINEL2_SR_START.isoformat()}."
                      if period.start < SENTINEL2_SR_START else "")
            warnings.append(_issue("no_compliant_sentinel2",
                                   f"No Sentinel-2 scene with cloud ≤ {source.max_cloud_pct:g}% and degraded MSI ≤ 0.1% in "
                                   f"the {name} window: the analysis can run, but its independent accuracy will not be "
                                   f"assessable.{reason}", name))
    shared = sorted(set(periods["target"].relative_orbits) & set(periods["baseline"].relative_orbits))
    return AnalysisPreflightResponse(ok=not blocking, target=periods["target"], baseline=periods["baseline"],
                                     shared_relative_orbits=shared, capacity=capacity, blocking=blocking, warnings=warnings)
