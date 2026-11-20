"""FRRIS Trend Analysis: the run-level record (docs/FRRIS_TREND_ANALYSIS_PLAN.md).

Opt-in context next to the flood map, like the modelled hazard and exposure: it never changes the flood map. Each
series is independent; a series that cannot be read is "not available" with its reason, and the others are still
delivered. The rules live in app/services/firris/trends.py and the Earth Engine reductions in
app/services/gee/trend_series.py (the Sentinel-1 water rule signed off on 2026-11-20).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Callable

from app.services.firris import trends
from app.services.gee import trend_series as ts

logger = logging.getLogger(__name__)

SERIES_ORDER = ("surface_water_annual", "rainfall_daily", "rainfall_dekadal", "sar_open_water")
UNAVAILABLE = "This series could not be read from the provider for this run; the other series and the flood map are unaffected."

JRC_SOURCE = ("Pekel, J.-F., Cottam, A., Gorelick, N., Belward, A. S. (2016). High-resolution mapping of global surface water "
              "and its long-term changes. Nature 540, 418–422. JRC Global Surface Water v1.4, YearlyHistory 1984–2021 "
              "(Google Earth Engine JRC/GSW1_4/YearlyHistory).")
CHIRPS_SOURCE = ("Funk, C. et al. (2015). The climate hazards infrared precipitation with stations — a new environmental record "
                 "for monitoring extremes. Scientific Data 2, 150066. CHIRPS daily v2.0 (Google Earth Engine "
                 "UCSB-CHG/CHIRPS/DAILY).")
S1_SOURCE = "Copernicus Sentinel-1 GRD, IW, VV (Google Earth Engine COPERNICUS/S1_GRD), the run's relative orbit."

S1_NAME = f"SAR open water (VV < {ts.WATER_THRESHOLD_DB:g} dB)"
S1_METHOD = (f"{S1_NAME}: VV backscatter after the run's {{radius}} m focal-median speckle filter; SRTM slope > "
             f"{ts.SLOPE_MAX_DEG:g}° excluded; area summed on the run's {{scale:g}} m grid. A pass covering less than "
             f"{ts.COVERAGE_MIN_PCT:g}% of the area is flagged. At most the latest {ts.MAX_PASSES} passes. Rule fixed "
             "before any series was computed (owner sign-off 2026-11-20).")
S1_CAVEATS = [
    "Not the FRRIS flood map and not accuracy-assessed.",
    "Can miss water roughened by wind and water under vegetation or trees.",
    "Can wrongly include smooth dry surfaces (some sand, tarmac, very dry bare soil).",
    "Use it for change over time, not as a flood map.",
]
JRC_CAVEATS = [
    "Surface water (seasonal and permanent) mapped from Landsat; not flood extent.",
    f"A year is flagged when more than {ts.NODATA_MAX_PCT:g}% of the surface-water footprint has no observation; flagged "
    "years are shown but not used for the trend line.",
]
CHIRPS_CAVEATS = [
    "CHIRPS cells are about 5.5 km; values are area-weighted means over the analysis area.",
    "Rainfall over the area only; rainfall upstream in the catchment is not included.",
]


def _last_day(period: dict) -> date:
    """API periods end exclusively: the last day included is end − 1."""
    return date.fromisoformat(str(period["end"])[:10]) - timedelta(days=1)


def _unavailable(key: str, title: str) -> dict[str, Any]:
    return {"key": key, "title": title, "status": "not_available", "reason": UNAVAILABLE}


def _guard(key: str, title: str, build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"status": "assessed", **build()}
    except Exception:  # noqa: BLE001 - provider failures are isolated per series
        logger.exception("Trend series %s could not be read", key)
        return _unavailable(key, title)


def run_trend_analysis(aoi_geometry: dict, *, target_period: dict, baseline_period: dict, orbit: int | None,
                       options: dict[str, Any] | None = None, scale: float = 30, speckle_radius_m: int = 50,
                       series_api=ts) -> dict[str, Any]:
    """The Trend Analysis record of one run. ``series_api`` is the Earth Engine module (replaced in tests)."""
    options = dict(options or {})
    rainfall_days = int(options.get("rainfall_days") or 90)
    target_last = _last_day(target_period)
    sar = options.get("sar_series") or {}
    sar_first = date.fromisoformat(str(sar.get("start") or baseline_period["start"])[:10])
    sar_last = _last_day(sar) if sar.get("end") else target_last
    ee = series_api.ee
    aoi = ee.Geometry(aoi_geometry)
    aoi_area_m2 = float(aoi.area(1).getInfo())

    def surface_water():
        points = series_api.jrc_annual(aoi, scale=scale)
        return trends.series_record(
            key="surface_water_annual", title="Surface-water extent, annual (JRC, 1984–2021)",
            indicator="Surface-water extent (seasonal + permanent)", units="km²", x_kind="year", points=points,
            axis_label="Surface water",
            source=JRC_SOURCE, method=(f"Area of JRC YearlyHistory classes 2 (seasonal) and 3 (permanent) inside the area, "
                                       f"summed on a {scale:g} m grid."),
            caveats=JRC_CAVEATS, fit_trend=True,
            columns={"seasonal_km2": "Seasonal water (km²)", "permanent_km2": "Permanent water (km²)",
                     "nodata_pct": "No data in the surface-water footprint (%)"})

    daily_points: list[dict] = []

    def rainfall_daily():
        daily_points.extend(series_api.chirps_daily(aoi, target_last, rainfall_days))
        return trends.series_record(
            key="rainfall_daily", title=f"Daily rainfall, {rainfall_days} days to {target_last:%d %b %Y}",
            indicator="Rainfall", units="mm/day", x_kind="date", points=daily_points, source=CHIRPS_SOURCE,
            method="CHIRPS daily precipitation, area-weighted mean over the area.", caveats=CHIRPS_CAVEATS, fit_trend=False,
            per="day")

    def rainfall_dekadal():
        points = trends.dekadal_totals(daily_points, target_last.isoformat()) if daily_points else []
        if not points:
            raise ValueError("no daily rainfall")
        return trends.series_record(
            key="rainfall_dekadal", title=f"10-day rainfall totals, {rainfall_days} days to {target_last:%d %b %Y}",
            indicator="Rainfall, 10-day total", units="mm per 10 days", x_kind="date", points=points, source=CHIRPS_SOURCE,
            method="Sum of the daily values in 10-day blocks ending on the target's last day; incomplete blocks flagged.",
            caveats=CHIRPS_CAVEATS, fit_trend=False, columns={"start": "First day", "end": "Last day"})

    def sar_open_water():
        result = series_api.s1_water_per_pass(aoi, aoi_area_m2, orbit, sar_first, sar_last, scale=scale,
                                              speckle_radius_m=speckle_radius_m)
        record = trends.series_record(
            key="sar_open_water", title=f"{S1_NAME} per Sentinel-1 pass", indicator=S1_NAME, units="km²", x_kind="date",
            axis_label="SAR open water",
            points=result["points"], source=S1_SOURCE, method=S1_METHOD.format(radius=speckle_radius_m, scale=scale),
            caveats=S1_CAVEATS, fit_trend=True,
            columns={"water_outside_permanent_km2": "Outside JRC permanent water (km²)", "coverage_pct": "Pass coverage (%)",
                     "steep_excluded_km2": "Steep ground excluded (km²)"})
        record.update(window={"first_day": sar_first.isoformat(), "last_day": sar_last.isoformat()}, orbit=orbit,
                      passes_in_window=len(result["pass_dates_in_window"]), passes_used=len(result["passes_used"]),
                      capped=result["capped"])
        return record

    series = {"surface_water_annual": _guard("surface_water_annual", "Surface-water extent, annual", surface_water),
              "rainfall_daily": _guard("rainfall_daily", "Daily rainfall", rainfall_daily)}
    series["rainfall_dekadal"] = _guard("rainfall_dekadal", "10-day rainfall totals", rainfall_dekadal)
    series["sar_open_water"] = (_guard("sar_open_water", S1_NAME, sar_open_water) if orbit is not None else
                                {**_unavailable("sar_open_water", S1_NAME), "reason": "The run has no single Sentinel-1 orbit."})
    anomaly_block: dict[str, Any] = {"status": "not_available", "reason": UNAVAILABLE}
    if series["rainfall_daily"]["status"] == "assessed":
        try:
            total = sum(p["value"] for p in daily_points if p.get("value") is not None)
            missing = sum(1 for p in daily_points if p.get("value") is None)
            climatology = series_api.chirps_climatology_total(aoi, target_last, rainfall_days)
            anomaly_block = {"status": "assessed", "window_days": rainfall_days, "last_day": target_last.isoformat(),
                             "missing_days": missing, "climatology_years": list(ts.CLIMATOLOGY_YEARS),
                             **trends.anomaly(total if not missing else None, climatology), "source": CHIRPS_SOURCE}
        except Exception:  # noqa: BLE001
            logger.exception("Rainfall climatology could not be read")
    assessed = [key for key in SERIES_ORDER if series[key]["status"] == "assessed"]
    return {
        "status": "assessed" if assessed else "not_available",
        "reason": None if assessed else "No trend series could be read for this run; the flood map is unaffected.",
        "method_version": trends.METHOD_VERSION, "rules": {
            "min_trend_points": trends.MIN_TREND_POINTS, "two_points": "Change, never Trend", "trend_line": trends.TREND_NOTE,
            "percent_change_zero_previous": "undefined"},
        "options": {"rainfall_days": rainfall_days, "sar_series": {"first_day": sar_first.isoformat(),
                                                                   "last_day": sar_last.isoformat()}},
        "series": series, "rainfall_anomaly": anomaly_block,
        "s1_rule": {"name": S1_NAME, "threshold_db": ts.WATER_THRESHOLD_DB, "speckle_radius_m": speckle_radius_m,
                    "slope_max_deg": ts.SLOPE_MAX_DEG, "coverage_min_pct": ts.COVERAGE_MIN_PCT, "max_passes": ts.MAX_PASSES,
                    "permanent_occurrence_pct": ts.PERMANENT_OCCURRENCE_PCT, "signed_off": "owner, 2026-11-20"},
        "datasets": [ts.JRC_YEARLY_ASSET, "UCSB-CHG/CHIRPS/DAILY", "COPERNICUS/S1_GRD", ts.JRC_OCCURRENCE_ASSET, "USGS/SRTMGL1_003"],
    }
