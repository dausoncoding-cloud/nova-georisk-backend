"""F12: degraded-MSI eligibility is enforced at scene selection, not by vetoing the whole window.

Synthetic provider metadata only; this proves selection logic, not field accuracy.
Policy: cloud <= max_cloud and DEGRADED_MSI_DATA_PERCENTAGE <= MAX_DEGRADED_MSI_PCT (0.1%,
client decision D6, 2026-11-11; previously 0%) for every scene that enters the composite.
"""
import copy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.gee import ingestion
from app.services.gee.scene_qa import MAX_DEGRADED_MSI_PCT, inspect_collection
from tests.unit.test_firris_bundle1 import AOI, scene


class _Predicate:
    def __init__(self, prop, test):
        self.prop, self.test = prop, test

    def __call__(self, record):
        return self.test(record["properties"][self.prop])


class _FakeCollection:
    """Minimal stand-in for ee.ImageCollection that evaluates filters on metadata records."""

    def __init__(self, records):
        self.records = list(records)

    def filterBounds(self, aoi):
        return self

    def filterDate(self, start, end):
        return self

    def filter(self, predicate):
        return _FakeCollection([record for record in self.records if predicate(record)])

    def sort(self, prop):
        return _FakeCollection(sorted(self.records, key=lambda record: record["properties"][prop]))

    def size(self):
        return SimpleNamespace(getInfo=lambda: len(self.records))

    def toList(self, count):
        return SimpleNamespace(getInfo=lambda: copy.deepcopy(self.records[:count]))


def _fake_ee(records):
    return SimpleNamespace(
        ImageCollection=lambda collection_id: _FakeCollection(records),
        Filter=SimpleNamespace(
            lte=lambda prop, value: _Predicate(prop, lambda observed: observed <= value),
            eq=lambda prop, value: _Predicate(prop, lambda observed: observed == value),
        ),
    )


def _s2(identifier, *, cloud=5.0, degraded=0.0):
    record = scene()
    record["id"] = f"{ingestion.SENTINEL2_COLLECTION}/{identifier}"
    record["properties"]["CLOUDY_PIXEL_PERCENTAGE"] = cloud
    record["properties"]["DEGRADED_MSI_DATA_PERCENTAGE"] = degraded
    return record


def _select_and_inspect(records, *, max_cloud=20.0, max_degraded_msi_pct=MAX_DEGRADED_MSI_PCT):
    with patch.object(ingestion, "ee", _fake_ee(records)):
        collection = ingestion.get_sentinel2_collection(
            MagicMock(name="aoi"), "2024-03-01", "2024-04-01",
            max_cloud_pct=max_cloud, max_degraded_msi_pct=max_degraded_msi_pct,
        )
        return inspect_collection(
            collection, sensor="Sentinel-2", period={"start": "2024-03-01", "end": "2024-04-01"},
            aoi=AOI, required_bands=["B3", "B8", "SCL"], max_cloud=max_cloud,
            collection_id=ingestion.SENTINEL2_COLLECTION,
        )


@patch("app.services.gee.ingestion.ee")
def test_query_filters_both_cloud_and_degraded_msi_when_required(mock_ee):
    collection = mock_ee.ImageCollection.return_value
    after_date = collection.filterBounds.return_value.filterDate.return_value
    after_cloud = after_date.filter.return_value
    after_degraded = after_cloud.filter.return_value

    result = ingestion.get_sentinel2_collection(
        MagicMock(), "2024-03-01", "2024-04-01", max_cloud_pct=20, max_degraded_msi_pct=MAX_DEGRADED_MSI_PCT
    )

    assert mock_ee.Filter.lte.call_args_list == [(("CLOUDY_PIXEL_PERCENTAGE", 20),), (("DEGRADED_MSI_DATA_PERCENTAGE", 0.1),)]
    after_date.filter.assert_called_once_with(mock_ee.Filter.lte.return_value)
    after_cloud.filter.assert_called_once_with(mock_ee.Filter.lte.return_value)
    after_degraded.sort.assert_called_once_with("CLOUDY_PIXEL_PERCENTAGE")
    assert result == after_degraded.sort.return_value


@patch("app.services.gee.ingestion.ee")
def test_default_query_is_unchanged_for_other_callers(mock_ee):
    ingestion.get_sentinel2_collection(MagicMock(), "2024-03-01", "2024-04-01", max_cloud_pct=20)
    mock_ee.Filter.lte.assert_called_once_with("CLOUDY_PIXEL_PERCENTAGE", 20)


def test_mixed_window_selects_only_compliant_scenes_instead_of_failing():
    records = [_s2("degraded", cloud=0.026, degraded=0.15), _s2("clean-a", cloud=3.0), _s2("clean-b", cloud=7.5)]

    result = _select_and_inspect(records)

    assert result["scene_count"] == 2
    pinned = [record["scene_id"] for record in result["scenes"]]
    assert pinned == [f"{ingestion.SENTINEL2_COLLECTION}/clean-a", f"{ingestion.SENTINEL2_COLLECTION}/clean-b"]
    assert all(record["degraded_msi_pct"] == 0 for record in result["scenes"])
    assert all(record["cloud_pct"] <= 20 for record in result["scenes"])


def test_cloud_gate_is_not_weakened_by_the_new_filter():
    records = [_s2("cloudy", cloud=20.5), _s2("clean", cloud=19.9)]
    result = _select_and_inspect(records)
    assert [record["scene_id"].rsplit("/", 1)[-1] for record in result["scenes"]] == ["clean"]


def test_window_with_only_degraded_scenes_fails_with_specific_reason():
    records = [_s2("degraded-a", degraded=0.11), _s2("degraded-b", degraded=0.25)]
    with pytest.raises(ValueError, match="No compliant optical scene"):
        _select_and_inspect(records)


def test_window_with_no_scene_under_cloud_limit_fails_with_specific_reason():
    with pytest.raises(ValueError, match="No compliant optical scene"):
        _select_and_inspect([_s2("cloudy", cloud=55.0)])


def test_per_scene_assertion_still_rejects_a_forged_degraded_record():
    # Defence in depth: if the provider query ever returned a degraded scene, the
    # per-scene QA must still refuse it (the old whole-window behaviour).
    with pytest.raises(ValueError, match="Optical scene cloud/sensor quality requirements are unmet"):
        _select_and_inspect([_s2("clean"), _s2("forged", degraded=0.11)], max_degraded_msi_pct=None)


def test_empty_sar_collection_keeps_generic_reason():
    collection = MagicMock()
    collection.size.return_value.getInfo.return_value = 0
    with pytest.raises(ValueError, match="Required collection is empty or exceeds bounded per-scene QA limit"):
        inspect_collection(collection, sensor="Sentinel-1", period={"start": "2024-03-01", "end": "2024-04-01"},
                           aoi=AOI, required_bands=["VV"])


def test_firris_pipeline_requests_query_level_degraded_filter_for_both_optical_periods(tmp_path, monkeypatch):
    from app.services.gee import firris_pipeline as pipeline

    calls = []

    class _Stop(Exception):
        pass

    def capture(aoi, start, end, **kwargs):
        calls.append({"start": start, **kwargs})
        if len(calls) == 1:
            raise ValueError("synthetic: no compliant optical scene")  # target unavailable -> reference only
        raise _Stop()

    sar_record = {"scene_count": 1, "scenes": [{"relative_orbit": 7, "scene_id": "synthetic"}]}
    monkeypatch.setattr(pipeline.auth, "initialize_gee", lambda: None)
    monkeypatch.setattr(pipeline.ingestion, "ee", MagicMock())
    monkeypatch.setattr(pipeline.ingestion, "build_aoi_geometry", lambda geometry: MagicMock())
    monkeypatch.setattr(pipeline.ingestion, "get_sentinel1_collection", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(pipeline, "inspect_collection", lambda collection, **kwargs: sar_record)
    monkeypatch.setattr(pipeline.ingestion, "get_sentinel2_collection", capture)
    config = {"date_mode": "pre-post", "target_period": {"start": "2024-03-05", "end": "2024-03-06"},
              "baseline_period": {"start": "2024-03-04", "end": "2024-03-05"}}

    with pytest.raises(_Stop):
        pipeline._fetch_feature_stack(config, AOI, tmp_path)

    assert calls == [{"start": "2024-03-05", "max_cloud_pct": 20.0, "max_degraded_msi_pct": 0.1},
                     {"start": "2024-03-04", "max_cloud_pct": 20.0, "max_degraded_msi_pct": 0.1}]
