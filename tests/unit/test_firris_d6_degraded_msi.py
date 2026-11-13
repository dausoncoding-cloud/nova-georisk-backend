"""Client decision D6 (2026-11-11): Sentinel-2 scenes with degraded MSI <= 0.1% are eligible.

Pixel-level protection is unchanged: SCL class 1 (saturated/defective) and the cloud,
shadow, cirrus and snow classes stay masked in every pixel. Cloud <= 20% is unchanged.
"""
from unittest.mock import MagicMock

import pytest

from app.services.gee import ingestion, preprocessing
from app.services.gee import firris_pipeline as pipeline
from app.services.gee.scene_qa import MAX_DEGRADED_MSI_PCT
from tests.unit.test_firris_f12_scene_eligibility import _s2, _select_and_inspect


def test_threshold_is_one_constant_of_point_one_percent():
    assert MAX_DEGRADED_MSI_PCT == 0.1
    assert pipeline.MAX_DEGRADED_MSI_PCT is MAX_DEGRADED_MSI_PCT


@pytest.mark.parametrize("degraded", [0.0, 0.02, 0.0213, 0.1])
def test_scene_at_or_below_point_one_percent_is_accepted(degraded):
    result = _select_and_inspect([_s2("scene", degraded=degraded)])
    assert result["scene_count"] == 1 and result["scenes"][0]["degraded_msi_pct"] == degraded


@pytest.mark.parametrize("degraded", [0.11, 0.5, 1.0])
def test_scene_above_point_one_percent_is_excluded_by_the_query(degraded):
    result = _select_and_inspect([_s2("clean"), _s2("degraded", degraded=degraded)])
    assert [scene["scene_id"].rsplit("/", 1)[-1] for scene in result["scenes"]] == ["clean"]


def test_per_scene_assertion_uses_the_same_threshold():
    with pytest.raises(ValueError, match="Optical scene cloud/sensor quality requirements are unmet"):
        _select_and_inspect([_s2("forged", degraded=0.11)], max_degraded_msi_pct=None)
    assert _select_and_inspect([_s2("ok", degraded=0.1)], max_degraded_msi_pct=None)["scene_count"] == 1


def test_cloud_gate_is_unchanged_at_twenty_percent():
    result = _select_and_inspect([_s2("cloudy", cloud=20.01, degraded=0.02), _s2("clear", cloud=20.0, degraded=0.02)])
    assert [scene["scene_id"].rsplit("/", 1)[-1] for scene in result["scenes"]] == ["clear"]


def test_scl_class_one_saturated_or_defective_pixels_stay_masked():
    image = MagicMock(name="s2")
    scl = image.select.return_value
    preprocessing.mask_sentinel2_clouds(image)
    image.select.assert_called_with("SCL")
    excluded = [call.args[0] for call in scl.neq.call_args_list]
    assert 1 in excluded and {0, 3, 8, 9, 10, 11} <= set(excluded)
    image.updateMask.assert_called_once()


def test_pipeline_and_ingestion_share_the_threshold():
    import inspect
    assert "max_degraded_msi_pct=MAX_DEGRADED_MSI_PCT" in inspect.getsource(pipeline)
    assert "DEGRADED_MSI_DATA_PERCENTAGE" in inspect.getsource(ingestion.get_sentinel2_collection)
