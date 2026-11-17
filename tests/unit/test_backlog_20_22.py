"""Backlog §4.7 items 20–22 (wording), included in r6."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.api.v1.result_overview import NO_SCENE_TEXT, _quality_gates
from app.services.firris import preflight
from app.services.reporting.scientific_report import _gate_row
from tests.unit.test_scientific_report import _pdf_text, _run


# --- item 20: "Not applicable (no compliant scene)" instead of "Not recorded" ------------------------------------

def _gates(quality):
    return {g["name"]: g for g in _quality_gates({}, quality, {})}


def test_no_sentinel2_scene_makes_the_optical_gates_not_applicable():
    gates = _gates({"scene_counts": {"sentinel_2_target": 0, "sentinel_2_baseline": 0}, "per_collection": {}})
    for name in ("Sentinel-2 cloud cover", "Sentinel-2 degraded MSI"):
        assert gates[name]["status"] == "not_applicable" and gates[name]["observed"] == NO_SCENE_TEXT
        assert _gate_row(gates[name], "not_assessable")[2:] == ["—", "Not applicable (no compliant scene)"]


def test_older_results_without_scene_counts_stay_not_recorded():
    gates = _gates({"per_collection": {}})
    assert gates["Sentinel-2 cloud cover"]["status"] == "not_recorded"
    assert _gate_row(gates["Sentinel-2 cloud cover"], "assessed")[3] == "Not recorded"


def test_recorded_scenes_are_still_measured():
    scene = {"cloud_pct": 1.2, "degraded_msi_pct": 0.0, "acquired_at": "2024-05-24"}
    quality = {"scene_counts": {"sentinel_2_target": 1, "sentinel_2_baseline": 0}, "max_cloud_pct": 20,
               "per_collection": {"sentinel_2_target": {"scenes": [scene]}}}
    assert _gates(quality)["Sentinel-2 cloud cover"]["status"] == "pass"


# --- item 21: the long reason in full once, short pointers elsewhere ------------------------------------------------

REASON = "Sentinel-2 target: No compliant optical scene in the requested window (cloud, degraded MSI or QA)"


def test_the_independent_reason_appears_once_in_the_report(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, optical_status={"status": "unavailable", "periods": {}, "reason": REASON})
    text = _pdf_text(tmp_path / result.output_files["scientific_report_pdf"]["path"])
    assert text.count(REASON) == 1
    accuracy = text[text.index("9. Accuracy assessment"):text.index("10. Limitations")]
    assert REASON in accuracy  # in full where the reason matters
    summary = text[text.index("1. Executive summary"):text.index("2. Study area")]
    assert "the reason is given in section 9" in summary
    assert "(reason in section 9)" in text[text.index("6. Quality gates"):text.index("7. Main maps")]
    assert "(reason in section 9)" in text[text.index("10. Limitations"):text.index("11. Provenance")]


# --- item 22: the nearest passes are dates, not limits ---------------------------------------------------------------

def _message(before, after):
    ok = SimpleNamespace(sentinel1_pass_dates=[date(2023, 9, 1)], nearest_pass_before=None, nearest_pass_after=None,
                         start=date(2023, 9, 1), end=date(2023, 9, 2), relative_orbits=[57])
    target = SimpleNamespace(sentinel1_pass_dates=[], nearest_pass_before=before, nearest_pass_after=after,
                             start=date(2024, 5, 20), end=date(2024, 5, 22), relative_orbits=[])
    return preflight._orbit_issues({"target": target, "baseline": ok})[0].message


@pytest.mark.parametrize("before, after, expected", [
    (date(2024, 5, 13), date(2024, 5, 25), "Nearest usable passes: 13 May 2024 (before the window) and 25 May 2024 (after)."),
    (None, date(2024, 5, 25), "Nearest usable pass: 25 May 2024 (after the window)."),
    (date(2024, 5, 13), None, "Nearest usable pass: 13 May 2024 (before the window)."),
    (None, None, "No usable pass within 90 days either side."),
])
def test_nearest_pass_wording(before, after, expected):
    message = _message(before, after)
    assert message.startswith("No Sentinel-1 pass over this area between 20 and 21 May 2024. ") and message.endswith(expected)
    assert "before 13 May" not in message
