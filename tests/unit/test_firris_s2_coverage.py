"""Sentinel-2 reference coverage: the preflight uses the run's exact eligibility and AOI-coverage rule.

Kilombero May 2024 (real GEE, 2026-11-15) showed the gap this closes: three compliant granules
existed, so the preflight reported Sentinel-2 as available, but they covered only 88% of the AOI
(tiles 36LZR, 37MBM), so the run's reference was not assessable. Synthetic metadata only here.
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.analyses import SatelliteSourceConfig
from app.services.firris import preflight
from app.services.gee import auth, ingestion, scene_qa
from tests.unit.test_firris_f12_scene_eligibility import _FakeCollection, _fake_ee

# A two-tile AOI (0.10 x 0.05 degrees): tile A covers x 0..0.06 and tile B x 0.04..0.10 (they overlap,
# as MGRS tiles do).
AOI = {"type": "Polygon", "coordinates": [[[0, 0], [0.1, 0], [0.1, 0.05], [0, 0.05], [0, 0]]]}
TILE_A = {"type": "LinearRing", "coordinates": [[-0.01, -0.01], [0.06, -0.01], [0.06, 0.06], [-0.01, 0.06], [-0.01, -0.01]]}
TILE_B = {"type": "LinearRing", "coordinates": [[0.04, -0.01], [0.11, -0.01], [0.11, 0.06], [0.04, 0.06], [0.04, -0.01]]}
PERIOD = {"start": "2024-05-01", "end": "2024-06-01"}
BASELINE = {"start": "2024-04-01", "end": "2024-05-01"}


class _DatedCollection(_FakeCollection):
    """Also applies filterDate, so each window sees only its own granules."""

    def filterDate(self, start, end):
        def day(record):
            return datetime.fromtimestamp(record["properties"]["system:time_start"] / 1000, timezone.utc).date().isoformat()
        return _DatedCollection([r for r in self.records if start <= day(r) < end])

    def filter(self, predicate):
        return _DatedCollection(super().filter(predicate).records)

    def sort(self, prop):
        return _DatedCollection(super().sort(prop).records)


def _dated_ee(records):
    fake = _fake_ee(records)
    fake.ImageCollection = lambda collection_id: _DatedCollection(records)
    return fake


def granule(tile, footprint, day, cloud=5.0, degraded=0.0, month=5):
    bands = [{"id": name, "crs": "EPSG:32737", "crs_transform": [s, 0, 0, 0, -s, 100]}
             for name, s in (("B3", 10), ("B11", 20), ("SCL", 20))]
    stamp = datetime(2024, month, day, 7, 30, tzinfo=timezone.utc).timestamp() * 1000
    return {"id": f"{ingestion.SENTINEL2_COLLECTION}/2024{month:02d}{day:02d}_{tile}", "bands": bands,
            "properties": {"system:time_start": stamp, "system:footprint": footprint, "MGRS_TILE": tile,
                           "CLOUDY_PIXEL_PERCENTAGE": cloud, "DEGRADED_MSI_DATA_PERCENTAGE": degraded}}


def qa(records, monkeypatch, max_cloud=20):
    monkeypatch.setattr(ingestion, "ee", _dated_ee(records))
    return scene_qa.optical_reference_qa(None, AOI, PERIOD, max_cloud)


# Coverage rule -----------------------------------------------------------------------------------
def test_aoi_coverage_is_the_runs_rule_and_never_rounds_partial_up_to_100():
    a, b = scene_qa.footprint_polygon(TILE_A), scene_qa.footprint_polygon(TILE_B)
    assert scene_qa.aoi_coverage(AOI, [a, b]) == (True, 100.0)
    assert scene_qa.aoi_coverage(AOI, [a]) == (False, 60.0)
    assert scene_qa.aoi_coverage(AOI, []) == (False, 0.0)
    sliver = scene_qa.footprint_polygon({"type": "Polygon", "coordinates": [[[-1, -1], [0.09999, -1], [0.09999, 2], [-1, 2], [-1, -1]]]})
    assert scene_qa.aoi_coverage(AOI, [sliver]) == (False, 99.9)


# Two-tile AOI ------------------------------------------------------------------------------------
def test_two_tiles_on_one_date_cover_the_aoi(monkeypatch):
    record = qa([granule("37MBM", TILE_A, 2), granule("36LZR", TILE_B, 2)], monkeypatch)
    assert record["footprint_coverage"] == "complete" and record["aoi_coverage_pct"] == 100.0
    assert record["tiles"] == ["36LZR", "37MBM"] and record["acquisition_dates"] == ["2024-05-02"]
    assert scene_qa.granule_summary(record) == "2 granules on 1 date (2 tiles)"
    assert scene_qa.require_complete_cover(record) is record


def test_one_clear_tile_of_two_is_partial_and_the_run_rejects_it(monkeypatch):
    # Tile B is clear only on a cloudy date (35% > 20%), so it is not eligible.
    record = qa([granule("37MBM", TILE_A, 2), granule("37MBM", TILE_A, 7), granule("36LZR", TILE_B, 7, cloud=35)], monkeypatch)
    assert record["footprint_coverage"] == "partial" and record["aoi_coverage_pct"] == 60.0
    assert scene_qa.granule_summary(record) == "2 granules on 2 dates (1 tile)"
    with pytest.raises(ValueError, match="Missing scene tiles"):
        scene_qa.require_complete_cover(record)


def test_degraded_granule_is_not_eligible_for_cover(monkeypatch):
    record = qa([granule("37MBM", TILE_A, 2), granule("36LZR", TILE_B, 2, degraded=0.5)], monkeypatch)
    assert record["tiles"] == ["37MBM"] and record["footprint_coverage"] == "partial"


def test_summary_wording():
    record = {"scene_count": 4, "acquisition_dates": ["2024-05-17"], "tiles": ["36LZR", "37MBM"]}
    assert scene_qa.granule_summary(record) == "4 granules on 1 date (2 tiles)"
    assert scene_qa.granule_summary({"scene_count": 1, "acquisition_dates": ["d"], "tiles": ["t"]}) == "1 granule on 1 date (1 tile)"


# The run and the preflight share one function ---------------------------------------------------
def _provider(monkeypatch, s2_records):
    """Fake Earth Engine for preflight.scene_availability: one S1 pass on orbit 57 in each window.
    The baseline window always has a full two-tile cover, so only the target varies."""
    s1 = SimpleNamespace(aggregate_array=lambda prop: prop)
    fake = _dated_ee(s2_records + [granule("37MBM", TILE_A, 10, month=4), granule("36LZR", TILE_B, 10, month=4)])
    fake.Dictionary = lambda d: SimpleNamespace(getInfo=lambda: {
        "times": [datetime(2024, 5, 20, tzinfo=timezone.utc).timestamp() * 1000], "orbits": [57],
        "s2": d["s2"].getInfo()})
    monkeypatch.setattr(ingestion, "ee", fake)
    monkeypatch.setattr(ingestion, "get_sentinel1_collection", lambda *a, **k: s1)
    monkeypatch.setattr(ingestion, "build_aoi_geometry", lambda geometry: geometry)
    monkeypatch.setattr(auth, "initialize_gee", lambda: None)
    calls = []
    real = scene_qa.optical_reference_qa
    monkeypatch.setattr(scene_qa, "optical_reference_qa", lambda *a: calls.append(a) or real(*a))
    return calls


def _source():
    return SatelliteSourceConfig(provider="gee", target_period=PERIOD, baseline_period=BASELINE, scale=30, max_cloud_pct=20)


def test_preflight_warns_when_the_reference_would_be_partial(monkeypatch):
    calls = _provider(monkeypatch, [granule("37MBM", TILE_A, 2), granule("36LZR", TILE_B, 7, cloud=35)])
    result = preflight.run_preflight(aoi_geometry=AOI, source=_source(), today=date(2026, 11, 15))
    assert len(calls) == 2  # once per window, through the run's function
    assert result.ok and result.blocking == []
    target = result.target
    assert target.sentinel2_tiles == ["37MBM"] and target.sentinel2_aoi_coverage_pct == 60.0
    assert target.sentinel2_dates == [date(2024, 5, 2)] and target.sentinel2_summary == "1 granule on 1 date (1 tile)"
    warning = next(w for w in result.warnings if w.period == "target")
    assert warning.code == "sentinel2_partial_coverage"
    assert "cover only 60% of the area: 1 granule on 1 date (1 tile: 37MBM)" in warning.message
    assert "independent accuracy will not be assessable" in warning.message


def test_preflight_is_quiet_when_the_reference_covers_the_aoi(monkeypatch):
    _provider(monkeypatch, [granule("37MBM", TILE_A, 2), granule("36LZR", TILE_B, 2)])
    result = preflight.run_preflight(aoi_geometry=AOI, source=_source(), today=date(2026, 11, 15))
    assert result.ok and result.warnings == []
    assert result.target.sentinel2_summary == "2 granules on 1 date (2 tiles)" and result.target.sentinel2_aoi_coverage_pct == 100.0


def test_preflight_and_run_give_the_same_record(monkeypatch):
    records = [granule("37MBM", TILE_A, 2), granule("36LZR", TILE_B, 2)]
    run_record = qa(records, monkeypatch)
    calls = _provider(monkeypatch, records)
    preflight.run_preflight(aoi_geometry=AOI, source=_source(), today=date(2026, 11, 15))
    assert scene_qa.optical_reference_qa(*calls[0]) == run_record


def test_scenes_failing_per_scene_qa_warn_without_internals(monkeypatch):
    bad = granule("37MBM", TILE_A, 2)
    bad["bands"] = bad["bands"][:1]  # lacks B11 and SCL
    _provider(monkeypatch, [bad])
    result = preflight.run_preflight(aoi_geometry=AOI, source=_source(), today=date(2026, 11, 15))
    warning = next(w for w in result.warnings if w.period == "target")
    assert warning.code == "sentinel2_partial_coverage" and "do not pass the quality checks" in warning.message
    assert "B11" not in warning.message and "band" not in warning.message.lower()
