"""Trend Analysis record of a run, with a fake Earth Engine series module (no provider calls)."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.analyses import FIRRISContextConfig, FIRRISTrendAnalysisConfig
from app.services.firris.trend_analysis import S1_NAME, run_trend_analysis
from app.services.gee import trend_series as real

AOI = {"type": "Polygon", "coordinates": [[[38.92, -7.99], [39.01, -7.99], [39.01, -7.90], [38.92, -7.90], [38.92, -7.99]]]}
TARGET = {"start": "2024-05-24", "end": "2024-05-26"}
BASELINE = {"start": "2022-08-28", "end": "2022-09-03"}


class FakeEE:
    class Geometry:
        def __init__(self, geometry):
            self.geometry = geometry

        def area(self, _):
            return SimpleNamespace(getInfo=lambda: 99.19e6)


def fake_api(*, fail=(), calls=None):
    calls = calls if calls is not None else {}

    def jrc_annual(aoi, scale=30):
        if "jrc" in fail:
            raise RuntimeError("provider down")
        return [real.jrc_point(y, [{"class": 2, "sum": (1 + 0.1 * (y - 2000)) * 1e6}, {"class": 0, "sum": 5e6 if y < 2003 else 0}])
                for y in range(2000, 2012)]

    def chirps_daily(aoi, last_day, days):
        calls["rain"] = (last_day, days)
        if "chirps" in fail:
            raise RuntimeError("provider down")
        return [{"t": (last_day - timedelta(days=days - 1 - i)).isoformat(), "value": 2.0, "flagged": False} for i in range(days)]

    def chirps_climatology_total(aoi, last_day, days):
        return 100.0

    def s1_water_per_pass(aoi, area, orbit, first, last, *, scale, speckle_radius_m):
        calls["s1"] = (orbit, first, last, scale, speckle_radius_m)
        points = [real.s1_point({"t": f"2024-0{m}-01", "data": area, "water": m * 1e6}, area) for m in range(1, 8)]
        return {"pass_dates_in_window": [p["t"] for p in points], "passes_used": [p["t"] for p in points], "capped": False,
                "points": points}

    return SimpleNamespace(ee=SimpleNamespace(Geometry=FakeEE.Geometry), jrc_annual=jrc_annual, chirps_daily=chirps_daily,
                           chirps_climatology_total=chirps_climatology_total, s1_water_per_pass=s1_water_per_pass)


def test_the_record_holds_the_four_series_the_anomaly_and_the_rule():
    calls = {}
    record = run_trend_analysis(AOI, target_period=TARGET, baseline_period=BASELINE, orbit=57, options={"rainfall_days": 30},
                                scale=30, speckle_radius_m=50, series_api=fake_api(calls=calls))
    assert record["status"] == "assessed"
    assert list(record["series"]) == ["surface_water_annual", "rainfall_daily", "rainfall_dekadal", "sar_open_water"]
    water = record["series"]["surface_water_annual"]
    assert water["units"] == "km²" and water["n_flagged"] == 3 and water["summary"]["kind"] == "trend"
    assert water["summary"]["trend"]["slope"] == pytest.approx(0.1)  # flagged 2000–2002 are not fitted
    daily = record["series"]["rainfall_daily"]
    assert daily["n_points"] == 30 and "trend" not in daily["summary"]
    assert calls["rain"] == (date(2024, 5, 25), 30)  # the window ends on the target's last day (API end − 1)
    assert record["rainfall_anomaly"]["total_mm"] == 60.0 and record["rainfall_anomaly"]["anomaly_percent"] == pytest.approx(-40.0)
    sar = record["series"]["sar_open_water"]
    assert sar["indicator"] == S1_NAME == "SAR open water (VV < -18 dB)" and sar["orbit"] == 57
    assert "Not the FRRIS flood map and not accuracy-assessed." in sar["caveats"]
    assert calls["s1"] == (57, date(2022, 8, 28), date(2024, 5, 25), 30, 50)  # default window: baseline start to target end
    assert record["s1_rule"]["threshold_db"] == -18.0 and record["s1_rule"]["signed_off"] == "owner, 2026-11-20"


def test_a_failing_series_is_isolated():
    record = run_trend_analysis(AOI, target_period=TARGET, baseline_period=BASELINE, orbit=57, series_api=fake_api(fail={"jrc"}))
    assert record["status"] == "assessed"
    assert record["series"]["surface_water_annual"]["status"] == "not_available"
    assert record["series"]["rainfall_daily"]["status"] == "assessed"


def test_without_a_single_orbit_the_sar_series_is_not_available():
    record = run_trend_analysis(AOI, target_period=TARGET, baseline_period=BASELINE, orbit=None, series_api=fake_api())
    assert record["series"]["sar_open_water"]["status"] == "not_available"
    assert "single Sentinel-1 orbit" in record["series"]["sar_open_water"]["reason"]


def test_when_everything_fails_the_record_says_so():
    api = fake_api(fail={"jrc", "chirps"})
    record = run_trend_analysis(AOI, target_period=TARGET, baseline_period=BASELINE, orbit=None, series_api=api)
    assert record["status"] == "not_available" and "flood map is unaffected" in record["reason"]


def test_a_custom_sar_window_uses_the_inclusive_last_day():
    calls = {}
    run_trend_analysis(AOI, target_period=TARGET, baseline_period=BASELINE, orbit=57,
                       options={"sar_series": {"start": "2023-10-01", "end": "2024-07-01"}}, series_api=fake_api(calls=calls))
    assert calls["s1"][1:3] == (date(2023, 10, 1), date(2024, 6, 30))


def test_options_schema():
    assert FIRRISTrendAnalysisConfig().rainfall_days == 90
    with pytest.raises(ValidationError):
        FIRRISTrendAnalysisConfig(rainfall_days=45)
    with pytest.raises(ValidationError):
        FIRRISTrendAnalysisConfig(sar_series={"start": "2014-01-01", "end": "2015-01-01"})
    assert FIRRISContextConfig().trend_analysis is None
    assert FIRRISContextConfig(trend_analysis={}).trend_analysis.rainfall_days == 90
