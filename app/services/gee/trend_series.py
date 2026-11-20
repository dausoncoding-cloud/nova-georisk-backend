"""Trend Analysis series from Earth Engine (docs/FRRIS_TREND_ANALYSIS_PLAN.md §1, §3.1).

Server-side reductions only (small JSON, no rasters), bounded:
* T1 JRC YearlyHistory: 38 annual area sums;
* T2 CHIRPS: at most 180 daily AOI means, plus a 30-year climatology total of the same calendar window;
* T3 Sentinel-1: at most MAX_PASSES pass dates on the run's orbit, water area under the signed-off rule (§3.1).

The Sentinel-1 water rule (signed off by the owner, 2026-11-20) is fixed here and nowhere else:
VV < WATER_THRESHOLD_DB after the run's focal-median speckle filter; SRTM slope > SLOPE_MAX_DEG excluded; a pass covering
< COVERAGE_MIN_PCT of the AOI is flagged; JRC occurrence >= PERMANENT_OCCURRENCE_PCT is reported as permanent water.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.services.gee import ingestion, preprocessing

JRC_YEARLY_ASSET = "JRC/GSW1_4/YearlyHistory"
JRC_OCCURRENCE_ASSET = "JRC/GSW1_4/GlobalSurfaceWater"
CLIMATOLOGY_YEARS = (1991, 2020)
MAX_RAIN_DAYS = 180
MAX_PASSES = 24
WATER_THRESHOLD_DB = -18.0
SLOPE_MAX_DEG = 5.0
COVERAGE_MIN_PCT = 70.0
NODATA_MAX_PCT = 30.0
PERMANENT_OCCURRENCE_PCT = 90
CHIRPS_SCALE_M = 5566  # native CHIRPS cell (0.05°); the area-weighted mean handles AOIs smaller than a cell
KM2 = 1e-6

ee = ingestion.ee


def _area_by_class(image, aoi, scale: float) -> "ee.Dictionary":
    """Area (m²) per integer class of a single-band image inside the AOI."""
    grouped = ee.Image.pixelArea().addBands(image).reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class"), geometry=aoi, scale=scale, maxPixels=1e10)
    return grouped


def jrc_annual(aoi, scale: float = 30) -> list[dict[str, Any]]:
    """T1: seasonal + permanent water (classes 2 and 3) per year, flagged when > 30% of the surface-water footprint
    (pixels ever seen as water, classes 0–3) has no data that year."""
    collection = ee.ImageCollection(JRC_YEARLY_ASSET)

    def per_year(image):
        groups = _area_by_class(image.select("waterClass"), aoi, scale).get("groups")
        return ee.Feature(None, {"year": image.get("year"), "groups": groups})

    rows = ee.FeatureCollection(collection.map(per_year)).getInfo()["features"]
    points = [jrc_point(int(row["properties"]["year"]), row["properties"].get("groups") or []) for row in rows]
    return sorted(points, key=lambda p: p["t"])


def jrc_point(year: int, groups: list[dict]) -> dict[str, Any]:
    """One T1 point from the per-class areas (m²) of a YearlyHistory year."""
    area = {int(g["class"]): float(g["sum"]) for g in groups}
    # YearlyHistory masks pixels where water was never seen in 1984–2021, so water can only appear inside the
    # unmasked "surface-water footprint" (classes 0–3). The flag is the share of that footprint with no data in the
    # year (class 0): when it is large, the year's water area is underestimated.
    footprint = sum(area.get(k, 0.0) for k in (0, 1, 2, 3))
    nodata_pct = area.get(0, 0.0) / footprint * 100 if footprint else 100.0
    flagged = nodata_pct > NODATA_MAX_PCT
    return {"t": year, "value": (area.get(2, 0.0) + area.get(3, 0.0)) * KM2,
            "seasonal_km2": area.get(2, 0.0) * KM2, "permanent_km2": area.get(3, 0.0) * KM2,
            "footprint_km2": footprint * KM2, "nodata_pct": nodata_pct, "flagged": flagged,
            "flag": f"{nodata_pct:.1f}% of the surface-water footprint has no data (> {NODATA_MAX_PCT:g}%)" if flagged else None}


def _window(last_day: date, days: int) -> tuple[date, date]:
    """[first day, day after the last day): ``days`` days ending on ``last_day``."""
    return last_day - timedelta(days=days - 1), last_day + timedelta(days=1)


def chirps_daily(aoi, last_day: date, days: int) -> list[dict[str, Any]]:
    """T2: daily area-weighted AOI mean rainfall (mm) for the ``days`` days ending on ``last_day``."""
    if not 1 <= days <= MAX_RAIN_DAYS:
        raise ValueError(f"Rainfall window must be 1–{MAX_RAIN_DAYS} days")
    start, end = _window(last_day, days)
    collection = ingestion.get_chirps_rainfall(aoi, start.isoformat(), end.isoformat())
    rows = ee.FeatureCollection(collection.map(lambda image: ee.Feature(None, {
        "t": image.date().format("YYYY-MM-dd"),
        "mm": image.select("precipitation").reduceRegion(ee.Reducer.mean(), aoi, CHIRPS_SCALE_M).get("precipitation")}))).getInfo()
    by_day = {f["properties"]["t"]: f["properties"].get("mm") for f in rows["features"]}
    points = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        value = by_day.get(day)
        points.append({"t": day, "value": None if value is None else float(value), "flagged": value is None,
                       "flag": "no CHIRPS value" if value is None else None})
    return points


def chirps_climatology_total(aoi, last_day: date, days: int) -> float | None:
    """Mean over 1991–2020 of the rainfall total in the same calendar window (``days`` days ending on the same day)."""
    month, day = last_day.month, last_day.day
    if (month, day) == (2, 29):
        month, day = 2, 28

    def total(year):
        end = ee.Date.fromYMD(year, month, day).advance(1, "day")
        start = end.advance(-days, "day")
        image = ee.ImageCollection(ingestion.CHIRPS_COLLECTION).filterDate(start, end).select("precipitation").sum()
        return image.reduceRegion(ee.Reducer.mean(), aoi, CHIRPS_SCALE_M).get("precipitation")

    values = [v for v in ee.List.sequence(*CLIMATOLOGY_YEARS).map(total).getInfo() if v is not None]
    return float(sum(values) / len(values)) if values else None


def s1_point(sums: dict, aoi_area_m2: float) -> dict[str, Any]:
    """One T3 point from the per-pass area sums (m²): data, steep, water, water outside JRC permanent water."""
    coverage = (sums.get("data") or 0.0) / aoi_area_m2 * 100 if aoi_area_m2 else 0.0
    flagged = coverage < COVERAGE_MIN_PCT
    return {"t": sums["t"], "value": (sums.get("water") or 0.0) * KM2,
            "water_outside_permanent_km2": (sums.get("water_outside_permanent") or 0.0) * KM2,
            "coverage_pct": coverage, "steep_excluded_km2": (sums.get("steep") or 0.0) * KM2,
            "scenes": sums.get("scenes") or [], "flagged": flagged,
            "flag": f"pass covers {coverage:.1f}% of the area (< {COVERAGE_MIN_PCT:g}%)" if flagged else None}


def s1_pass_dates(aoi, orbit: int, start: date, last_day: date) -> list[str]:
    """Distinct pass dates on the run's orbit (ascending, IW, VV) in [start, last_day]."""
    collection = (ingestion.get_sentinel1_collection(aoi, start.isoformat(), (last_day + timedelta(days=1)).isoformat())
                  .filter(ee.Filter.eq("relativeOrbitNumber_start", int(orbit))))
    dates = collection.aggregate_array("system:time_start").map(lambda t: ee.Date(t).format("YYYY-MM-dd")).distinct()
    return sorted(dates.getInfo())


def s1_water_per_pass(aoi, aoi_area_m2: float, orbit: int, start: date, last_day: date, *, scale: float = 30,
                      speckle_radius_m: int = 50) -> dict[str, Any]:
    """T3: SAR open water (VV < −18 dB) per pass under the signed-off rule; at most MAX_PASSES latest passes."""
    dates = s1_pass_dates(aoi, orbit, start, last_day)
    capped = dates[-MAX_PASSES:]
    slope_ok = ee.Terrain.slope(ee.Image(ingestion.SRTM_DEM_ASSET)).lte(SLOPE_MAX_DEG)
    permanent = ee.Image(JRC_OCCURRENCE_ASSET).select("occurrence").unmask(0).gte(PERMANENT_OCCURRENCE_PCT)
    base = (ingestion.get_sentinel1_collection(aoi, start.isoformat(), (last_day + timedelta(days=1)).isoformat())
            .filter(ee.Filter.eq("relativeOrbitNumber_start", int(orbit))))

    def per_date(day):
        day = ee.Date.parse("YYYY-MM-dd", day)
        scenes = base.filterDate(day, day.advance(1, "day"))
        vv = preprocessing.apply_speckle_filter(scenes.select("VV").mosaic(), speckle_radius_m)
        has_data = vv.mask().gt(0)
        valid = has_data.And(slope_ok)
        water = vv.lt(WATER_THRESHOLD_DB).And(valid)
        stack = ee.Image.cat(
            ee.Image.pixelArea().updateMask(has_data).rename("data"),
            ee.Image.pixelArea().updateMask(has_data.And(slope_ok.Not())).rename("steep"),
            ee.Image.pixelArea().updateMask(water).rename("water"),
            ee.Image.pixelArea().updateMask(water.And(permanent.Not())).rename("water_outside_permanent"))
        sums = stack.reduceRegion(ee.Reducer.sum(), aoi, scale, maxPixels=1e10)
        return ee.Feature(None, sums.combine({"t": day.format("YYYY-MM-dd"),
                                               "scenes": scenes.aggregate_array("system:index")}))

    rows = ee.FeatureCollection(ee.List(capped).map(per_date)).getInfo()["features"] if capped else []
    points = [s1_point(row["properties"], aoi_area_m2) for row in rows]
    return {"pass_dates_in_window": dates, "passes_used": capped, "capped": len(dates) > MAX_PASSES,
            "points": sorted(points, key=lambda p: p["t"])}
