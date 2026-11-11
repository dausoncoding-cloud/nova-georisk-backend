"""1.6: results produced before firris-science-2 carry a read-time interpretation notice.

Nothing stored is altered; the notice is derived when the result is serialized.
"""
import copy
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.serializers import LEGACY_FIRRIS_NOTICE, serialize_result
from app.schemas.results import ResultResponse

EXPECTED_NOTICE = (
    "Produced before the JRC never-water correction; analysis was restricted to historically wet pixels. "
    "Metrics are internal agreement with SAR screening labels. Downloaded files from this run use older labels "
    "(“Flood Probability”, “Flood Risk Index Summary”); the score is a model confidence score, "
    "not a probability of flooding."
)
GEE_LEGACY_PROVENANCE = {"engine_key": "firris", "per_scene_lineage": {"sentinel_2_target": {"scene_count": 1}},
                         "label_source": "SAR screening pseudo-label; not independent ground truth"}


def _result(*, engine_key="firris", provenance=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(id=uuid.uuid4(), task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=None,
                           engine_key=engine_key, result_type="flood_mapping", version=1, summary={"status": "completed"},
                           output_files={}, provenance=provenance, created_at=now, updated_at=now)


def test_notice_text_is_exact():
    assert LEGACY_FIRRIS_NOTICE == EXPECTED_NOTICE


def test_legacy_gee_result_gets_notice_without_mutating_stored_provenance():
    provenance = copy.deepcopy(GEE_LEGACY_PROVENANCE)
    result = _result(provenance=provenance)
    response = serialize_result(result)
    assert response.interpretation_notice == EXPECTED_NOTICE
    assert result.provenance == GEE_LEGACY_PROVENANCE
    assert "interpretation_notice" not in (result.summary or {})


def test_firris_science_2_result_gets_no_notice():
    response = serialize_result(_result(provenance={**GEE_LEGACY_PROVENANCE, "science_version": "firris-science-2"}))
    assert response.interpretation_notice is None


@pytest.mark.parametrize("provenance", [
    {"engine_key": "firris", "provider": "prepared_rasters", "label_source": "reviewed labels"},
    {"engine_key": "firris", "workflow": "direct product calculation"},
    None,
])
def test_non_gee_firris_results_get_no_notice(provenance):
    assert serialize_result(_result(provenance=provenance)).interpretation_notice is None


def test_other_engines_get_no_notice():
    assert serialize_result(_result(engine_key="source_bound", provenance=dict(GEE_LEGACY_PROVENANCE))).interpretation_notice is None


def test_field_is_optional_so_existing_payloads_still_validate():
    now = datetime.now(timezone.utc)
    payload = {"id": uuid.uuid4(), "task_id": uuid.uuid4(), "project_id": uuid.uuid4(), "aoi_id": None,
               "engine_key": "firris", "result_type": "flood_mapping", "version": 1, "summary": {},
               "provenance": {}, "products": [], "layers": [], "exports": [], "created_at": now, "updated_at": now}
    assert ResultResponse.model_validate(payload).interpretation_notice is None


def test_serializer_and_pipeline_agree_on_science_version():
    from app.api.v1.serializers import FIRRIS_SCIENCE_VERSION as serializer_version
    from app.services.gee.firris_pipeline import FIRRIS_SCIENCE_VERSION as pipeline_version
    assert serializer_version == pipeline_version == "firris-science-2"
