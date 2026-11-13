"""2.3: computed result overview (headline, area accounting, quality gates, data sources). No new science."""
import copy
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.result_overview import build_result_overview
from app.api.v1.serializers import serialize_result
from app.schemas.results import ResultOverview, ResultResponse


def _scene(scene_id, date, **checks):
    return {"scene_id": scene_id, "acquired_at": date, **checks}


SUMMARY = {
    "status": "completed",
    "products": {"flood_extent": {"area_statistics": {
        "valid_cells": 110889, "valid_area_km2": 97.73, "valid_area_ha": 9773.0,
        "flooded_area_km2": 5.339, "flooded_percent_of_valid": 5.4367,
        "class_areas": [{"class_value": 0, "area_ha": 9239.1}, {"class_value": 1, "area_ha": 533.9}]}}},
    "quality": {
        "status": "passed", "valid_pixel_coverage_pct": 99.402, "aoi_cells": 111556, "valid_aoi_cells": 110889,
        "missing_cells_by_band": {"0": 600, "1": 667, "11": 1500}, "minimum_valid_coverage_pct": 70.0, "max_cloud_pct": 20.0,
        "admission_bands": ["sar_vv_target", "sar_change"],
        "optical_reference": {"status": "available", "reason": None},
        "per_collection": {
            "sentinel_1_target": {"scenes": [_scene("COPERNICUS/S1_GRD/S1A_t", "2024-05-25", relative_orbit=57)]},
            "sentinel_1_baseline": {"scenes": [_scene("COPERNICUS/S1_GRD/S1A_b", "2022-08-28", relative_orbit=57)]},
            "sentinel_2_target": {"scenes": [_scene("COPERNICUS/S2_SR_HARMONIZED/T", "2024-05-24", cloud_pct=4.6, degraded_msi_pct=0.0)]},
            "sentinel_2_baseline": {"scenes": [_scene("COPERNICUS/S2_SR_HARMONIZED/B", "2022-09-02", cloud_pct=7.0, degraded_msi_pct=0.0)]},
            "chirps_target": {"scene_count": 2, "scenes": [_scene("c1", "2024-05-24"), _scene("c2", "2024-05-25")]},
        },
    },
    "validation_dashboard": {"kind": "binary", "metrics": {}, "availability": {}, "plots": [], "scope": "declared_holdout",
                             "units": "binary_class_0_1", "independent_validation": "assessed",
                             "limitations": ["Metrics describe supplied paired observations only."]},
    "independent_accuracy": {"status": "assessed", "reason": None},
    "model": {"algorithm": "random_forest"},
}
PROVENANCE = {
    "engine_key": "firris", "science_version": "firris-science-2", "per_scene_lineage": {},
    "target_period": {"start": "2024-05-24", "end": "2024-05-26"}, "baseline_period": {"start": "2022-08-28", "end": "2022-09-03"},
    "band_identity": ["sar_vv_target", "sar_change", "elevation", "slope", "rainfall", "source_sar_baseline", "source_sar_target",
                      "label", "jrc_occurrence", "source_mndwi_target", "source_mndwi_baseline", "optical_reference"],
    "datasets": ["COPERNICUS/S1_GRD", "COPERNICUS/S2_SR_HARMONIZED", "JRC/GSW1_4/GlobalSurfaceWater", "UCSB-CHG/CHIRPS/DAILY", "USGS/SRTMGL1_003"],
    "sampling": {"minimum_per_class": 30, "class_counts": {"0": 4600, "1": 400}},
}


def _result(summary=SUMMARY, provenance=PROVENANCE, engine_key="firris"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(id=uuid.uuid4(), task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=None, engine_key=engine_key,
                           result_type="flood_mapping", version=1, summary=copy.deepcopy(summary), output_files={},
                           provenance=copy.deepcopy(provenance), created_at=now, updated_at=now)


def test_headline_states_value_denominator_dates_and_meaning():
    headline = build_result_overview(_result())["headline"]
    assert headline["text"] == ("Model-classified flood candidates cover 5.34 km² (5.44% of the 97.73 km² valid analysed area) "
                                "for target 2024-05-24 to 2024-05-26, compared with baseline 2022-08-28 to 2022-09-03 (end dates exclusive). "
                                "Flood candidates are a model classification trained on SAR screening labels, not confirmed flood observations.")
    assert headline["flood_candidate_area_km2"] == pytest.approx(5.339)


def test_area_accounting_uses_cells_and_states_its_method():
    accounting = build_result_overview(_result())["area_accounting"]
    assert accounting["aoi_cells"] == 111556 and accounting["valid_cells"] == 110889 and accounting["excluded_cells"] == 667
    assert accounting["valid_pct_of_aoi"] == pytest.approx(99.402)
    assert accounting["flood_candidate_pct_of_valid"] == pytest.approx(5.4367)
    assert accounting["flood_candidate_pct_of_aoi"] == pytest.approx(5.339 / (97.73 / 110889 * 111556) * 100)
    assert accounting["aoi_area_km2_estimate"] == pytest.approx(97.73 / 110889 * 111556)
    assert "mean valid-cell area" in accounting["method_note"]
    bands = {row["band"]: row for row in accounting["missing_cells_by_band"]}
    assert bands["sar_change"]["cells"] == 667 and bands["optical_reference"]["cells"] == 1500
    assert bands["optical_reference"]["affects_admission"] is False and bands["sar_change"]["affects_admission"] is True


def test_quality_gate_table_reports_threshold_observed_and_status():
    gates = {gate["name"]: gate for gate in build_result_overview(_result())["quality_gates"]}
    assert gates["Valid pixel coverage"] == {"name": "Valid pixel coverage", "threshold": "≥ 70%", "observed": "99.40%", "status": "pass"}
    assert gates["Sentinel-2 cloud cover"]["observed"] == "max 7.0% over 2 scenes" and gates["Sentinel-2 cloud cover"]["status"] == "pass"
    assert gates["Sentinel-2 degraded MSI"]["threshold"] == "= 0%" and gates["Sentinel-2 degraded MSI"]["status"] == "pass"
    assert gates["Sentinel-1 relative orbit match"]["observed"] == "target 57; baseline 57" and gates["Sentinel-1 relative orbit match"]["status"] == "pass"
    assert gates["Class support"]["observed"] == "class 0: 4600; class 1: 400" and gates["Class support"]["status"] == "pass"
    assert gates["Daily rainfall completeness"]["observed"] == "2 of 2 days" and gates["Daily rainfall completeness"]["status"] == "pass"
    assert gates["Independent reference"]["status"] == "pass"


def test_missing_records_are_not_recorded_never_guessed():
    summary = copy.deepcopy(SUMMARY); summary["quality"] = {"status": "passed", "valid_pixel_coverage_pct": 91.7}
    summary.pop("independent_accuracy"); summary["validation_dashboard"] = {}
    provenance = {"engine_key": "firris", "per_scene_lineage": {}}
    overview = build_result_overview(_result(summary, provenance))
    gates = {gate["name"]: gate for gate in overview["quality_gates"]}
    assert gates["Valid pixel coverage"]["status"] == "pass" and gates["Valid pixel coverage"]["threshold"] == "≥ 70%"
    assert gates["Sentinel-1 relative orbit match"] == {"name": "Sentinel-1 relative orbit match", "threshold": "one orbit, same in both periods", "observed": None, "status": "not_recorded"}
    assert gates["Independent reference"]["status"] == "not_recorded"
    assert "dates not recorded" in overview["headline"]["text"]


def test_failing_and_not_assessable_gates_are_reported_as_such():
    summary = copy.deepcopy(SUMMARY)
    summary["quality"]["valid_pixel_coverage_pct"] = 65.0
    summary["independent_accuracy"] = {"status": "not_assessable", "reason": "Sentinel-2 baseline: No compliant optical scene"}
    gates = {gate["name"]: gate for gate in build_result_overview(_result(summary))["quality_gates"]}
    assert gates["Valid pixel coverage"]["status"] == "fail"
    assert gates["Independent reference"] == {"name": "Independent reference", "threshold": "compliant Sentinel-2 at both dates; ≥ 50 eligible pixels per class",
                                              "observed": "not assessable: Sentinel-2 baseline: No compliant optical scene", "status": "not_applicable"}


def test_data_sources_list_dataset_dates_resolution_and_credit():
    sources = {item["dataset"]: item for item in build_result_overview(_result())["data_sources"]}
    s1 = sources["COPERNICUS/S1_GRD"]
    assert s1["scene_dates"] == ["2022-08-28", "2024-05-25"] and s1["resolution"] == "10 m (IW GRD)"
    assert s1["credit"] == "Contains modified Copernicus Sentinel data 2022, 2024"
    assert sources["COPERNICUS/S2_SR_HARMONIZED"]["scene_dates"] == ["2022-09-02", "2024-05-24"]
    assert sources["UCSB-CHG/CHIRPS/DAILY"]["scene_dates"] == ["2024-05-24", "2024-05-25"]
    assert set(sources) == set(PROVENANCE["datasets"]) | {"JRC/GSW1_4/Metadata"}


def test_run_specific_limitations_come_first():
    summary = copy.deepcopy(SUMMARY)
    summary["independent_accuracy"] = {"status": "insufficient_reference_samples", "reason": "Fewer than 50 eligible non-training reference pixels in a class"}
    limitations = build_result_overview(_result(summary))["limitations"]
    assert limitations[0].startswith("Independent accuracy: insufficient reference samples")
    assert limitations[-1] == "Metrics describe supplied paired observations only."


def test_only_firris_flood_results_get_an_overview_and_it_validates_and_serializes():
    assert build_result_overview(_result(engine_key="source_bound")) is None
    assert build_result_overview(_result(summary={"status": "completed", "products": {}})) is None
    ResultOverview.model_validate(build_result_overview(_result()))
    response = serialize_result(_result())
    assert isinstance(response, ResultResponse) and response.overview is not None
    json.dumps(response.model_dump(mode="json"), allow_nan=False)


def test_overview_is_null_when_not_applicable():
    payload = serialize_result(_result(engine_key="source_bound")).model_dump(mode="json")
    assert payload["overview"] is None


def test_degraded_msi_gate_uses_the_threshold_recorded_by_the_run():
    summary = copy.deepcopy(SUMMARY)
    summary["quality"]["degraded_msi_max_pct"] = 0.1  # client decision D6
    summary["quality"]["per_collection"]["sentinel_2_target"]["scenes"][0]["degraded_msi_pct"] = 0.02
    gates = {gate["name"]: gate for gate in build_result_overview(_result(summary))["quality_gates"]}
    assert gates["Sentinel-2 degraded MSI"] == {"name": "Sentinel-2 degraded MSI", "threshold": "≤ 0.1% per scene",
                                                "observed": "max 0.02% over 2 scenes", "status": "pass"}


def test_legacy_results_without_a_recorded_threshold_keep_the_zero_percent_gate():
    gates = {gate["name"]: gate for gate in build_result_overview(_result())["quality_gates"]}
    assert gates["Sentinel-2 degraded MSI"]["threshold"] == "= 0%" and gates["Sentinel-2 degraded MSI"]["status"] == "pass"
    summary = copy.deepcopy(SUMMARY)
    summary["quality"]["per_collection"]["sentinel_2_target"]["scenes"][0]["degraded_msi_pct"] = 0.02
    gates = {gate["name"]: gate for gate in build_result_overview(_result(summary))["quality_gates"]}
    assert gates["Sentinel-2 degraded MSI"]["status"] == "fail"


@pytest.mark.parametrize("products", [[{"product_key": "flood_hazard"}], "not-a-dict", None, {"flood_extent": ["x"]},
                                      {"flood_extent": {"area_statistics": ["x"]}}])
def test_overview_tolerates_non_dict_product_summaries(products):
    summary = {"status": "completed", "products": products}
    assert build_result_overview(_result(summary=summary)) is None
    assert serialize_result(_result(summary=summary)).overview is None
