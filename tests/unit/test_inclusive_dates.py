"""P6 (2026-11-16): every user-facing period is inclusive; API fields and provenance stay exclusive.

Last day shown = exclusive end − 1 day. Rufiji (target 2024-05-24 → 2024-05-26, baseline 2022-08-28 → 2022-09-03)
reads "24–25 May 2024" and "28 Aug – 2 Sep 2022".
"""
from datetime import date

import pytest

from app.services.reporting.dates import between_text, day_text, last_day, period_dict_text, period_text
from tests.unit.test_scientific_report import _pdf_text

RUFIJI_TARGET = {"start": "2024-05-24", "end": "2024-05-26"}
RUFIJI_BASELINE = {"start": "2022-08-28", "end": "2022-09-03"}


@pytest.mark.parametrize(("end", "last"), [
    ("2024-05-26", date(2024, 5, 25)),
    ("2024-03-01", date(2024, 2, 29)),   # leap year
    ("2023-03-01", date(2023, 2, 28)),
    ("2024-01-01", date(2023, 12, 31)),  # year boundary
    (date(2022, 9, 3), date(2022, 9, 2)),
])
def test_last_day_is_the_exclusive_end_minus_one_day(end, last):
    assert last_day(end) == last


def test_rufiji_reads_inclusive():
    assert period_dict_text(RUFIJI_TARGET) == "24–25 May 2024"
    assert period_dict_text(RUFIJI_BASELINE) == "28 Aug – 2 Sep 2022"


@pytest.mark.parametrize(("start", "end", "text", "between"), [
    ("2024-05-24", "2024-05-25", "24 May 2024", "on 24 May 2024"),                                   # one day
    ("2024-05-21", "2024-05-23", "21–22 May 2024", "between 21 and 22 May 2024"),
    ("2022-08-28", "2022-09-03", "28 Aug – 2 Sep 2022", "between 28 Aug and 2 Sep 2022"),
    ("2023-12-30", "2024-01-03", "30 Dec 2023 – 2 Jan 2024", "between 30 Dec 2023 and 2 Jan 2024"),
    ("2024-03-01", "2024-04-01", "1–31 Mar 2024", "between 1 and 31 Mar 2024"),
])
def test_period_and_message_wording(start, end, text, between):
    assert period_text(start, end) == text
    assert between_text(start, end) == between


def test_invalid_or_empty_windows_are_not_invented():
    assert period_text("2024-05-24", "2024-05-24") is None  # empty window: no last day
    assert period_dict_text(None) is None and period_dict_text({"start": "2024-05-24"}) is None
    assert day_text(None) == "not recorded"


def test_result_overview_sentence_is_inclusive_and_the_api_fields_stay_exclusive():
    from app.api.v1.result_overview import _headline

    headline = _headline({"flooded_area_km2": 5.34, "flooded_percent_of_valid": 5.44, "valid_area_km2": 98.21},
                         {"target_period": RUFIJI_TARGET, "baseline_period": RUFIJI_BASELINE})
    assert "for target 24–25 May 2024, compared with baseline 28 Aug – 2 Sep 2022." in headline["text"]
    assert "exclusive" not in headline["text"]
    assert headline["target_period"] == "2024-05-24 to 2024-05-26"      # API field unchanged (exclusive)
    assert headline["baseline_period"] == "2022-08-28 to 2022-09-03"


def test_scientific_report_shows_inclusive_periods(tmp_path, monkeypatch):
    import uuid

    from app.platform.engines.base import EngineExecutionContext
    from app.platform.engines.firris import FIRRISEngineAdapter
    from app.services.gee import firris_pipeline as pipeline
    from tests.unit.test_firris_independent_accuracy import AOI, _gee_stack

    def stack(*args, **kwargs):
        built = _gee_stack(None)
        # As fetch_feature_stack records them: the API's exclusive windows.
        built.provenance.update(target_period=RUFIJI_TARGET, baseline_period=RUFIJI_BASELINE)
        return built

    monkeypatch.setattr(pipeline, "fetch_feature_stack", stack)
    result = FIRRISEngineAdapter().execute(EngineExecutionContext(
        task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), output_directory=tmp_path,
        operation="flood_mapping", products=["flood_extent", "flood_probability"], aoi_geometry=AOI,
        project_name="Rufiji flood study", aoi_name="Rufiji floodplain 2024",
        parameters={"workflow": {"source": {"provider": "gee", "features": ["sar_change", "slope", "rainfall"],
                                            "target_period": RUFIJI_TARGET, "baseline_period": RUFIJI_BASELINE},
                                 "sampling": {"sample_size": 300, "min_per_class": 40, "train_fraction": 0.7, "random_seed": 3},
                                 "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 20}}},
        gis_metadata={"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -1.6, "east": 36.6, "north": -1},
                      "spatial_resolution": {"x": 0.01, "y": 0.01, "unit": "degree"}, "producer": "NOVA GeoRisk"},
        result_version=1), lambda _: None)
    # Provenance and the science keep the exclusive windows.
    assert result.provenance["target_period"] == RUFIJI_TARGET and result.provenance["baseline_period"] == RUFIJI_BASELINE
    text = _pdf_text(tmp_path / result.output_files["scientific_report_pdf"]["path"])
    assert "Model-classified flood candidates cover" in text and "for target 24–25 May 2024, compared with baseline 28 Aug – 2 Sep 2022." in text
    assert "Target: 24–25 May 2024; baseline: 28 Aug – 2 Sep 2022. Both periods include their last day." in text
    assert "Target 24–25 May 2024; baseline 28 Aug – 2 Sep 2022." in text  # map captions
    assert "exclusive" not in text
