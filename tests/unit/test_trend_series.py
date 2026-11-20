"""Trend Analysis series: the signed-off Sentinel-1 rule and the per-point arithmetic (no Earth Engine calls)."""
from datetime import date

import pytest

from app.services.gee import trend_series as ts


def test_the_signed_off_sentinel1_rule_is_fixed():
    # docs/FRRIS_TREND_ANALYSIS_PLAN.md §3.1, signed off by the owner on 2026-11-20. Changing any value needs a new
    # written rule and sign-off; this test fails on purpose if a value is edited.
    assert (ts.WATER_THRESHOLD_DB, ts.SLOPE_MAX_DEG, ts.COVERAGE_MIN_PCT, ts.MAX_PASSES, ts.PERMANENT_OCCURRENCE_PCT) == (
        -18.0, 5.0, 70.0, 24, 90)
    assert ts.NODATA_MAX_PCT == 30.0 and ts.CLIMATOLOGY_YEARS == (1991, 2020)


def test_jrc_point_water_area_and_footprint_no_data_share():
    groups = [{"class": 0, "sum": 4e6}, {"class": 1, "sum": 2e6}, {"class": 2, "sum": 3e6}, {"class": 3, "sum": 1e6}]
    point = ts.jrc_point(2010, groups)
    assert point["value"] == pytest.approx(4.0) and point["seasonal_km2"] == pytest.approx(3.0)
    assert point["footprint_km2"] == pytest.approx(10.0) and point["nodata_pct"] == pytest.approx(40.0)
    assert point["flagged"] and "40.0% of the surface-water footprint has no data" in point["flag"]


def test_jrc_year_without_any_observation_is_flagged_not_reported_as_dry():
    point = ts.jrc_point(1988, [{"class": 0, "sum": 5e6}])
    assert point["value"] == 0.0 and point["nodata_pct"] == 100.0 and point["flagged"]
    assert ts.jrc_point(1990, [])["flagged"]


def test_s1_point_coverage_flag_and_areas():
    sums = {"t": "2024-04-19", "data": 99e6, "steep": 1e6, "water": 13.39e6, "water_outside_permanent": 12e6, "scenes": ["S1A_x"]}
    point = ts.s1_point(sums, 100e6)
    assert point["value"] == pytest.approx(13.39) and point["water_outside_permanent_km2"] == pytest.approx(12.0)
    assert point["coverage_pct"] == pytest.approx(99.0) and not point["flagged"]
    low = ts.s1_point({"t": "2024-04-07", "data": 60e6}, 100e6)
    assert low["flagged"] and low["value"] == 0.0 and "60.0% of the area" in low["flag"]


def test_rainfall_window_ends_on_the_target_last_day():
    assert ts._window(date(2024, 5, 25), 90) == (date(2024, 2, 26), date(2024, 5, 26))
    with pytest.raises(ValueError):
        ts.chirps_daily(None, date(2024, 5, 25), ts.MAX_RAIN_DAYS + 1)


def test_flagged_points_break_the_line_into_gaps():
    from app.services.reporting.trend_figures import segments
    pts = [{"t": 1984 + i, "value": 1.0, "flagged": i in (2, 3)} for i in range(7)]
    runs = segments(pts)
    assert [[p["t"] for p in run] for run in runs] == [[1984, 1985], [1988, 1989, 1990]]
