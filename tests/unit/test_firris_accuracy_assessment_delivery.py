"""2.2 delivery: accuracy tables reach the dashboard, CSV exports and the API without breaking legacy results."""

import pandas as pd
import pytest
from pydantic import ValidationError

from app.schemas.firris_evidence import AccuracyAssessment, ValidationDashboard
from app.schemas.results import ResultResponse
from tests.unit.test_firris_f2_internal_agreement import LEGACY_DASHBOARD, _result
from tests.unit.test_firris_f4_validation_rasters import _run_engine
from tests.unit.test_firris_independent_accuracy import _run_gee_engine


def _scopes(result):
    assessment = AccuracyAssessment.model_validate(result.summary["validation_dashboard"]["accuracy_assessment"])
    return assessment, {scope.scope: scope for scope in assessment.scopes}


def test_gee_run_delivers_independent_census_first_then_internal_agreement(tmp_path, monkeypatch):
    result = _run_gee_engine(tmp_path, monkeypatch)
    assessment, scopes = _scopes(result)
    assert [scope.scope for scope in assessment.scopes] == ["independent_optical", "internal_screening"]
    assert assessment.independent_status == "assessed"
    census, internal = scopes["independent_optical"], scopes["internal_screening"]
    accuracy = result.summary["independent_accuracy"]
    assert census.method == "census" and census.n == accuracy["metrics"]["n"]
    assert census.confusion_matrix.classified["1"].reference_1 == accuracy["metrics"]["confusion"]["tp"]
    assert census.overall_accuracy_pct == pytest.approx(accuracy["metrics"]["overall_accuracy_pct"])
    assert census.confidence_intervals_95 is None and "census" in census.interval_note
    samples = pd.read_csv(tmp_path / "samples.csv")
    assert internal.method == "held_out_sample" and internal.n == int((samples.sample_split == "test").sum())
    assert internal.confidence_intervals_95 is not None
    assert "Not field-verified" in assessment.independent_wording


def test_per_class_area_comes_from_the_classified_map(tmp_path, monkeypatch):
    result = _run_gee_engine(tmp_path, monkeypatch)
    _, scopes = _scopes(result)
    areas = {str(item["class_value"]): item["area_ha"] for item in result.summary["products"]["flood_extent"]["area_statistics"]["class_areas"]}
    for scope in scopes.values():
        rows = {row.class_label: row for row in scope.per_class}
        assert rows["1"].area_ha == pytest.approx(areas.get("1")) and rows["0"].area_ha == pytest.approx(areas.get("0"))


def test_tables_are_exported_as_csv_matching_the_dashboard(tmp_path, monkeypatch):
    result = _run_gee_engine(tmp_path, monkeypatch)
    _, scopes = _scopes(result)
    for name, scope in scopes.items():
        confusion = pd.read_csv(tmp_path / f"accuracy-{name}-confusion.csv")
        flooded_row = confusion[confusion["classified"] == "Flood candidate"].iloc[0]
        assert int(flooded_row["reference_flood_candidate"]) == scope.confusion_matrix.classified["1"].reference_1
        summary = pd.read_csv(tmp_path / f"accuracy-{name}-summary.csv")
        assert set(summary.columns) >= {"class", "area_ha", "omission_error_pct", "commission_error_pct",
                                        "users_accuracy_pct", "producers_accuracy_pct", "overall_accuracy_pct", "f1_score", "cohens_kappa"}
        assert len(pd.read_csv(tmp_path / f"accuracy-{name}-roc.csv")) == 101
        for suffix in ("confusion", "summary", "roc", "pr"):
            assert f"accuracy_{name}_{suffix}" in result.output_files


def test_not_assessable_run_keeps_internal_scope_and_states_the_reason(tmp_path, monkeypatch):
    status = {"status": "unavailable", "periods": {}, "reason": "Sentinel-2 baseline: No compliant optical scene in the requested window"}
    result = _run_gee_engine(tmp_path, monkeypatch, optical_status=status)
    assessment, scopes = _scopes(result)
    assert list(scopes) == ["internal_screening"]
    assert assessment.independent_status == "not_assessable" and assessment.independent_reason == status["reason"]


def test_prepared_run_has_internal_scope_labelled_as_supplied_labels(tmp_path):
    result, _ = _run_engine(tmp_path)
    assessment, scopes = _scopes(result)
    assert list(scopes) == ["internal_supplied"] and assessment.independent_status == "not_performed"


def test_legacy_dashboard_still_round_trips_and_schema_is_strict():
    payload = ResultResponse.model_validate(_result(dict(LEGACY_DASHBOARD))).model_dump(mode="json")
    assert payload["validation_dashboard"] == LEGACY_DASHBOARD
    with pytest.raises(ValidationError):
        ValidationDashboard.model_validate({**LEGACY_DASHBOARD, "accuracy_assessment": {"scopes": [], "unexpected": 1,
                                            "independent_status": "not_performed", "independent_reason": None, "independent_wording": None}})
