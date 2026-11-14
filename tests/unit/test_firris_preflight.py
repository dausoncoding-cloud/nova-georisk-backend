"""Plan items 4.4 / 4.1 / 4.6: metadata-only FIRRIS preflight (dates, Sentinel-1 orbit, Sentinel-2, capacity)."""
from datetime import date

import pytest

from app.schemas.analyses import SatelliteSourceConfig
from app.services.firris import preflight

TODAY = date(2026, 11, 14)
RUFIJI = {"type": "Polygon", "coordinates": [[[38.92, -7.99], [39.01, -7.99], [39.01, -7.90], [38.92, -7.90], [38.92, -7.99]]]}


def _source(target=("2024-05-24", "2024-05-26"), baseline=("2022-08-28", "2022-09-03"), scale=30, cloud=20):
    return SatelliteSourceConfig(provider="gee", target_period={"start": target[0], "end": target[1]},
                                 baseline_period={"start": baseline[0], "end": baseline[1]}, scale=scale, max_cloud_pct=cloud)


def _period(dates=(), orbits=(), s2=1, before=None, after=None):
    return {"sentinel1_pass_dates": [date.fromisoformat(d) for d in dates], "relative_orbits": list(orbits),
            "sentinel2_compliant_scenes": s2, "nearest_pass_before": before and date.fromisoformat(before),
            "nearest_pass_after": after and date.fromisoformat(after)}


@pytest.fixture
def availability(monkeypatch):
    calls = []

    def install(target, baseline):
        def fake(aoi_geometry, windows, max_cloud):
            calls.append((windows, max_cloud))
            return {"target": target, "baseline": baseline}
        monkeypatch.setattr(preflight, "scene_availability", fake)
        return calls
    return install


def codes(result, kind="blocking"):
    return [issue.code for issue in getattr(result, kind)]


# 4.4 sensor date bounds -------------------------------------------------------------------------
def test_dates_before_sentinel1_are_blocked_without_querying_gee(availability):
    calls = availability(_period(), _period())
    result = preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(("2014-06-01", "2014-06-10"), ("2013-06-01", "2013-06-10")), today=TODAY)
    assert not result.ok and codes(result).count("before_sentinel1_archive") == 2 and calls == []
    assert "3 October 2014" in result.blocking[0].message


def test_future_dates_are_blocked_without_querying_gee(availability):
    calls = availability(_period(), _period())
    result = preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(("2027-01-01", "2027-01-05"), ("2026-01-01", "2026-01-05")), today=TODAY)
    assert codes(result) == ["future_window"] and result.blocking[0].period == "target" and calls == []
    assert "after today" in result.blocking[0].message


@pytest.mark.parametrize("target, baseline, ok", [
    (("2024-05-24", "2024-05-26"), ("2014-10-03", "2014-10-05"), True),   # first Sentinel-1 day is allowed
    (("2024-05-24", "2024-05-26"), ("2014-10-02", "2014-10-05"), False),
    (("2026-11-13", "2026-11-15"), ("2022-08-28", "2022-09-03"), True),   # end is exclusive: last day = today
    (("2026-11-14", "2026-11-16"), ("2022-08-28", "2022-09-03"), False),  # last day is tomorrow
])
def test_date_boundaries(availability, target, baseline, ok):
    availability(_period(["2024-05-25"], [57]), _period(["2014-10-04"], [57]))
    result = preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(target, baseline), today=TODAY)
    assert not [c for c in codes(result) if c in {"before_sentinel1_archive", "future_window"}] == ok


# 4.1 Sentinel-1 orbit rules ---------------------------------------------------------------------
def test_matching_single_orbit_passes_and_reports_dates(availability):
    availability(_period(["2024-05-25"], [57], s2=1), _period(["2022-08-28"], [57], s2=2))
    result = preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(), today=TODAY)
    assert result.ok and result.blocking == [] and result.shared_relative_orbits == [57]
    assert result.target.sentinel1_pass_dates == [date(2024, 5, 25)] and result.baseline.sentinel2_compliant_scenes == 2


def test_empty_period_is_blocked_with_nearest_passes(availability):
    availability(_period(before="2024-05-13", after="2024-05-25"), _period(["2022-08-28"], [57]))
    result = preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(("2024-05-21", "2024-05-23")), today=TODAY)
    assert codes(result) == ["no_sentinel1_pass"] and result.blocking[0].period == "target"
    message = result.blocking[0].message
    assert "No Sentinel-1 pass" in message and "2024-05-13" in message and "2024-05-25" in message
    assert result.target.nearest_pass_before == date(2024, 5, 13) and result.target.nearest_pass_after == date(2024, 5, 25)


def test_orbit_mismatch_and_multiple_orbits_are_blocked(availability):
    availability(_period(["2024-05-25"], [57]), _period(["2022-08-28"], [130]))
    assert codes(preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(), today=TODAY)) == ["orbit_mismatch"]
    availability(_period(["2024-05-20", "2024-05-25"], [57, 130]), _period(["2022-08-28"], [57]))
    assert codes(preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(), today=TODAY)) == ["multiple_orbits"]


def test_missing_compliant_sentinel2_is_a_warning_only(availability):
    availability(_period(["2024-04-19"], [57], s2=0), _period(["2022-08-28"], [57], s2=2))
    result = preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(("2024-04-18", "2024-04-20")), today=TODAY)
    assert result.ok and codes(result, "warnings") == ["no_compliant_sentinel2"]
    assert "not assessable" in result.warnings[0].message and result.warnings[0].period == "target"


# 4.6 capacity -----------------------------------------------------------------------------------
def test_capacity_matches_staging_measurements():
    rufiji = preflight.capacity_estimate((38.92, -7.99, 39.01, -7.90), 30)
    assert 110_000 < rufiji["bbox_pixels"] < 115_000 and rufiji["estimated_request_bytes"] < preflight.REQUEST_LIMIT_BYTES
    manyoni = preflight.capacity_estimate((34.65, -5.90, 34.85, -5.70), 30)  # 0.2° square: 552,049 px measured
    assert 550_000 <= manyoni["bbox_pixels"] <= 556_000 and manyoni["estimated_request_bytes"] > preflight.REQUEST_LIMIT_BYTES


def test_oversize_area_is_blocked_with_split_advice(availability):
    calls = availability(_period(["2024-05-25"], [57]), _period(["2022-08-28"], [57]))
    big = {"type": "Polygon", "coordinates": [[[36.0, -7.0], [37.0, -7.0], [37.0, -6.0], [36.0, -6.0], [36.0, -7.0]]]}
    result = preflight.run_preflight(aoi_geometry=big, source=_source(), today=TODAY)
    assert codes(result) == ["capacity_exceeded"] and calls == []  # no GEE query for an area that cannot run
    assert "smaller area" in result.blocking[0].message and "split" in result.blocking[0].message
    assert result.capacity.ratio > 1


# Safety --------------------------------------------------------------------------------------
def test_provider_errors_and_timeouts_become_plain_messages(monkeypatch):
    def boom(*_):
        raise RuntimeError("ee.ee_exception.EEException: internal detail /secret/path")
    monkeypatch.setattr(preflight, "scene_availability", boom)
    with pytest.raises(preflight.PreflightUnavailable) as caught:
        preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(), today=TODAY)
    assert "EEException" not in str(caught.value) and "secret" not in str(caught.value)
    assert str(caught.value) == preflight.UNAVAILABLE_MESSAGE

    import time
    monkeypatch.setattr(preflight, "scene_availability", lambda *_: time.sleep(2))
    with pytest.raises(preflight.PreflightUnavailable):
        preflight.run_preflight(aoi_geometry=RUFIJI, source=_source(), today=TODAY, timeout=0.2)
