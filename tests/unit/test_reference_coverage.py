"""r6.1: the independent accuracy needs the eligible Sentinel-2 reference to cover >= REFERENCE_MIN_COVERAGE_PCT of the
valid analysed area (interim rule until D7). Bundle 5 (0c53d331): 0.42%, n = 454, was reported as 'assessed'."""
from types import SimpleNamespace

import numpy as np

from app.services.firris import reference_accuracy as ra
from app.services.firris.exposure import observed_extent_caveat
from app.services.firris.exposure_exports import map_caveat


def _assess(finite: int, shape=(100, 100)):
    rng = np.random.default_rng(1)
    reference = np.full(shape, np.nan)
    flat = reference.ravel()
    flat[:finite] = np.arange(finite) % 2
    predicted = rng.integers(0, 2, shape)
    return ra.assess_independent_accuracy(
        provider="gee", optical_status={"status": "available"}, reference=reference, valid_mask=np.ones(shape, bool),
        train_rows=[99], train_cols=[99], predicted_class=predicted, probability=rng.random(shape))


def test_the_threshold_lives_in_one_place():
    assert ra.REFERENCE_MIN_COVERAGE_PCT == 70.0


def test_bundle5_like_coverage_is_not_assessable_and_raw_figures_are_only_in_the_labelled_block():
    record, points = _assess(42)  # 0.42% of the analysed area, 21 pixels per class
    assert points is None
    assert record["status"] == "not_assessable" and record["coverage_rule"] == "failed"
    assert record["reason"] == ("The Sentinel-2 reference covers only 0.42% of the area (at least 70% of the valid analysed "
                                "area is required).")
    assert record["reference_coverage_text"] == "Eligible reference pixels cover 0.42% of the analysed area."
    assert "metrics" not in record and "audit_sample" not in record and "wording" not in record
    raw = record["unrepresentative_metrics"]
    assert raw["label"] == "not representative" and raw["metrics"]["n"] == 42 and "Not representative" in raw["note"]


def test_coverage_rule_comes_before_the_per_class_rule():
    record, _ = _assess(6000)  # 60% coverage, thousands of pixels per class
    assert record["status"] == "not_assessable" and record["coverage_rule"] == "failed"


def test_exactly_the_threshold_is_assessed_and_just_below_is_not():
    assert _assess(7000)[0]["status"] == "assessed"
    below = _assess(6999)[0]
    assert below["status"] == "not_assessable" and below["reference_coverage_pct"] < 70


def test_assessed_records_carry_the_coverage_sentence():
    record, _ = _assess(9879)
    assert record["status"] == "assessed" and record["reference_coverage_text"] == (
        "Eligible reference pixels cover 98.8% of the analysed area.")


def test_changing_the_constant_changes_the_rule(monkeypatch):
    monkeypatch.setattr(ra, "REFERENCE_MIN_COVERAGE_PCT", 50.0)
    assert _assess(6000)[0]["status"] == "assessed"


def _stored(fraction, ua=67.9):
    return {
        "independent_accuracy": {"status": "assessed", "reference_eligible_fraction": fraction, "eligible_cells": 468,
                                 "admitted_cells": 110889, "wording": "census of n = 454",
                                 "metrics": {"n": 454, "overall_accuracy_pct": 48.2, "cohens_kappa": -0.015, "roc_auc": 0.515},
                                 "audit_sample": {"per_class": {"0": 142, "1": 312}},
                                 "variable_roc": {"status": "not_assessable", "reason": "x", "curves": []}},
        "validation": {"independent_validation": "assessed"},
        "validation_dashboard": {"independent_validation": "assessed", "accuracy_assessment": {
            "independent_status": "assessed", "independent_reason": None, "independent_wording": "census of n = 454",
            "scopes": [{"scope": "independent_optical"}, {"scope": "internal_screening"}]}},
        "flood_exposure": {"status": "assessed", "observed_extent_caveat": observed_extent_caveat(ua)},
    }


def test_stored_bundle5_result_reads_as_not_assessable_without_rewriting_it():
    stored = _stored(468 / 110889)
    view = ra.summary_view(stored)
    assert stored["independent_accuracy"]["status"] == "assessed"  # the stored summary is untouched
    record = view["independent_accuracy"]
    assert record["status"] == "not_assessable" and record["reason"].startswith("The Sentinel-2 reference covers only 0.42%")
    assert "metrics" not in record and record["unrepresentative_metrics"]["metrics"]["overall_accuracy_pct"] == 48.2
    assert record["variable_roc"]["status"] == "not_assessable"
    assessment = view["validation_dashboard"]["accuracy_assessment"]
    assert assessment["independent_status"] == "not_assessable" and assessment["independent_wording"] is None
    assert [s["scope"] for s in assessment["scopes"]] == ["internal_screening"]
    assert view["validation"]["independent_validation"] == "not_assessable"
    caveat = view["flood_exposure"]["observed_extent_caveat"]
    assert caveat["users_accuracy_flood_pct"] is None and "67.9" not in caveat["text"]
    assert "not assessable for this run (the Sentinel-2 reference covers only 0.42% of the area)" in caveat["text"]


def test_stored_representative_result_is_unchanged_apart_from_the_coverage_sentence():
    view = ra.summary_view(_stored(0.9879, ua=48.9))
    assert view["independent_accuracy"]["status"] == "assessed"
    assert view["independent_accuracy"]["metrics"]["n"] == 454
    assert view["independent_accuracy"]["reference_coverage_text"] == "Eligible reference pixels cover 98.8% of the analysed area."
    assert view["flood_exposure"]["observed_extent_caveat"]["users_accuracy_flood_pct"] == 48.9


def test_stored_records_without_a_fraction_or_not_assessed_are_left_alone():
    old = {"independent_accuracy": {"status": "not_assessable", "reason": "no scene"}}
    assert ra.summary_view(old) == old
    insufficient = {"independent_accuracy": {"status": "insufficient_reference_samples", "reference_eligible_fraction": 0.1}}
    assert ra.summary_view(insufficient)["independent_accuracy"]["status"] == "insufficient_reference_samples"


def test_exposure_caveat_and_map_footer_use_the_not_assessable_text():
    reason = ra.not_representative({"reference_coverage_pct": 0.42}, None)["reason"]
    caveat = observed_extent_caveat(None, reason)
    assert map_caveat({"observed_extent_caveat": caveat}) == (
        "Flood candidates are model-classified: user's accuracy for flood not assessable (the Sentinel-2 reference covers "
        "only 0.42% of the area). Built-up areas may contain false positives.")
    assert "no Sentinel-2 reference" in map_caveat({"observed_extent_caveat": observed_extent_caveat(None)})


def test_results_page_gate_reports_the_coverage():
    from app.api.v1.result_overview import _quality_gates
    gates = _quality_gates(ra.summary_view(_stored(0.9879)), {}, {})
    gate = next(g for g in gates if g["name"] == "Independent reference")
    assert "eligible reference ≥ 70% of the analysed area" in gate["threshold"]
    assert gate["observed"].endswith("eligible reference pixels cover 98.8% of the analysed area")
    low = next(g for g in _quality_gates(ra.summary_view(_stored(0.0042)), {}, {}) if g["name"] == "Independent reference")
    assert low["status"] == "not_applicable" and "covers only 0.42%" in low["observed"]


def test_workbook_row():
    from app.platform.engines.firris import _reference_coverage_row
    row = _reference_coverage_row(_assess(42)[0])
    assert row["status"] == "not_assessable" and row["eligible_reference_pixels"] == 42 and row["minimum_coverage_pct"] == 70.0
    assert "metrics" not in row and "overall_accuracy_pct" not in row
