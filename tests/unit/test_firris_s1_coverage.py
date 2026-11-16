"""r5.1: Sentinel-1 radar coverage of the AOI, the same rule in the preflight and the run.

Production task efd93391 (Ugalla, 3,867 km², about 107 x 63 km): the single orbit-174 pass on each date covered
about 40% of the AOI (measured read-only on 2026-11-16), so the run failed with the generic message at 5% while
the preflight said Ready. Synthetic metadata here.
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.analyses import SatelliteSourceConfig
from app.services.firris import preflight
from app.services.firris.user_messages import public_error_summary
from app.services.gee import auth, ingestion
from app.services.gee.firris_pipeline import FIRRISQualityError
from app.services.gee.scene_qa import inspect_collection, sentinel1_coverage_message
from tests.unit.test_firris_bundle1 import scene

AOI = {"type": "Polygon", "coordinates": [[[0, 0], [1.0, 0], [1.0, 0.5], [0, 0.5], [0, 0]]]}
# The swath edge crosses the AOI: the pass covers x 0..0.4, i.e. 40% of it.
PARTIAL = {"type": "LinearRing", "coordinates": [[-0.1, -0.1], [0.4, -0.1], [0.4, 0.6], [-0.1, 0.6], [-0.1, -0.1]]}
FULL = {"type": "LinearRing", "coordinates": [[-0.1, -0.1], [1.1, -0.1], [1.1, 0.6], [-0.1, 0.6], [-0.1, -0.1]]}


def _s1(footprint, orbit=174):
    record = scene("Sentinel-1")
    record["id"] = f"{ingestion.SENTINEL1_COLLECTION}/S1A_fixture_{orbit}"
    record["properties"].update({"system:footprint": footprint, "relativeOrbitNumber_start": orbit,
                                 "system:time_start": datetime(2024, 4, 15, 16, 20, tzinfo=timezone.utc).timestamp() * 1000})
    return record


def _inspect(records):
    collection = MagicMock()
    collection.size.return_value.getInfo.return_value = len(records)
    collection.toList.return_value.getInfo.return_value = records
    return inspect_collection(collection, sensor="Sentinel-1", period={"start": "2024-04-15", "end": "2024-04-16"},
                              aoi=AOI, required_bands=["VV"], collection_id=ingestion.SENTINEL1_COLLECTION)


def test_run_refuses_a_partial_radar_cover_with_a_plain_allow_listed_message():
    with pytest.raises(ValueError) as caught:
        _inspect([_s1(PARTIAL)])
    message = str(caught.value)
    assert message == ("The Sentinel-1 radar pass on 15 Apr 2024 (orbit 174) covers only 40% of the area. FRRIS needs radar "
                       "from one orbit over the whole area in both windows. Split the area into parts (Area playground) or "
                       "trim it to the covered part.")
    assert public_error_summary(FIRRISQualityError(message)) == message  # shown to users, not the generic failure


def test_run_accepts_a_full_radar_cover():
    assert _inspect([_s1(FULL)])["footprint_coverage"] == "complete"


def _provider(monkeypatch, footprints, orbits=(174,)):
    monkeypatch.setattr(ingestion, "get_sentinel1_collection", lambda *a, **k: SimpleNamespace(aggregate_array=lambda prop: prop))
    monkeypatch.setattr(ingestion, "get_sentinel2_collection", lambda *a, **k: SimpleNamespace(size=lambda: 0))
    monkeypatch.setattr(ingestion, "build_aoi_geometry", lambda geometry: geometry)
    monkeypatch.setattr(auth, "initialize_gee", lambda: None)
    fake_ee = SimpleNamespace(Dictionary=lambda d: SimpleNamespace(getInfo=lambda: {
        "times": [datetime(2024, 4, 15, 16, 20, tzinfo=timezone.utc).timestamp() * 1000], "orbits": list(orbits),
        "footprints": footprints, "s2": 0}))
    monkeypatch.setattr(ingestion, "ee", fake_ee)


def _source():
    return SatelliteSourceConfig(provider="gee", target_period={"start": "2024-04-15", "end": "2024-04-16"},
                                 baseline_period={"start": "2023-09-12", "end": "2023-09-13"}, scale=120, max_cloud_pct=20)


def test_preflight_blocks_with_the_same_rule_and_wording(monkeypatch):
    _provider(monkeypatch, [PARTIAL])
    result = preflight.run_preflight(aoi_geometry=AOI, source=_source(), today=date(2026, 11, 16))
    assert not result.ok
    issues = [issue for issue in result.blocking if issue.code == "sentinel1_partial_coverage"]
    assert [issue.period for issue in issues] == ["target", "baseline"]
    assert issues[0].message == sentinel1_coverage_message("2024-04-15", "2024-04-16", 40.0, [174])
    assert "between" not in issues[1].message and "on 12 Sep 2023 (orbit 174) covers only 40% of the area" in issues[1].message
    dumped = result.model_dump_json()
    assert "_sentinel1_aoi_coverage_pct" not in dumped  # internal value, not part of the API


def test_preflight_is_quiet_when_the_pass_covers_the_area_or_footprints_are_missing(monkeypatch):
    _provider(monkeypatch, [FULL])
    assert "sentinel1_partial_coverage" not in [i.code for i in preflight.run_preflight(aoi_geometry=AOI, source=_source(), today=date(2026, 11, 16)).blocking]
    _provider(monkeypatch, [])  # no footprints returned: no coverage judgement rather than a false 0%
    assert "sentinel1_partial_coverage" not in [i.code for i in preflight.run_preflight(aoi_geometry=AOI, source=_source(), today=date(2026, 11, 16)).blocking]
