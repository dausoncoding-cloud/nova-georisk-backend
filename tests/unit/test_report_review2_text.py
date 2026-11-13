"""Client review 2: limitations, scope and repetition."""
import pytest

from tests.unit._report_run import report_run, section


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory, organization_name="Example Consulting Ltd", sample_report=True)


# Limitations: baseline distance from the target.
def test_baseline_gap_sentence_for_distant_or_off_season_baselines():
    from app.services.reporting.scientific_report import baseline_gap_text
    text = baseline_gap_text({"start": "2024-05-24", "end": "2024-05-26"}, {"start": "2022-08-28", "end": "2022-09-03"})
    assert "633 days before the target" in text and "97 days apart in the annual cycle" in text
    assert "seasonal changes" in text and "mixed with flooding" in text
    assert baseline_gap_text({"start": "2024-05-24", "end": "2024-05-26"}, {"start": "2024-05-01", "end": "2024-05-05"}) is None
    assert baseline_gap_text({"start": "2024-05-24", "end": "2024-05-26"}, {"start": "2023-05-20", "end": "2023-05-26"}) is not None  # > 90 days
    assert baseline_gap_text(None, {"start": "2022-08-28", "end": "2022-09-03"}) is None


# Scope list.
def test_scope_lists_jrc_water_classes(run):
    _, _, _, text, _, _ = run
    scope = section(text, "Scope of this report: not included in this version", "2. Study area")
    assert "Permanent and seasonal water classes (JRC) on the main map" in scope


# Repetition and noise removed.
def test_method_limitations_and_captions_are_not_repetitive(run):
    _, _, _, text, _, _ = run
    method = section(text, "5. Method", "6. Quality gates")
    assert method.count("stratified random") == 1
    assert "supplied paired observations" not in text
    assert "Threshold sweeps are descriptive operating points" in text  # other limitations stay
    assert "Coordinates and colour scale" not in text
