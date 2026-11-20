"""Trend Analysis end to end through the FRRIS engine (synthetic series; wiring, wording and files only).

The real Rufiji figures are checked in live QA (plan §7); here the Earth Engine series are replaced by fakes.
"""
import dataclasses
import uuid
from datetime import timedelta

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from app.platform.engines.base import EngineExecutionContext
from app.platform.engines.firris import FIRRISEngineAdapter
from app.services.gee import firris_pipeline as pipeline
from app.services.gee import trend_series as ts
from tests.unit.test_firris_independent_accuracy import AOI, _gee_stack


class _Area:
    def __init__(self, *_):
        pass

    def area(self, _):
        return type("V", (), {"getInfo": staticmethod(lambda: 60e6)})()


def _fake_series(monkeypatch):
    monkeypatch.setattr(ts, "ee", type("EE", (), {"Geometry": _Area}))
    monkeypatch.setattr(ts, "jrc_annual", lambda aoi, scale=30: [
        ts.jrc_point(y, [{"class": 2, "sum": (2 + 0.2 * (y - 2010)) * 1e6}]) for y in range(2010, 2022)])
    monkeypatch.setattr(ts, "chirps_daily", lambda aoi, last, days: [
        {"t": (last - timedelta(days=days - 1 - i)).isoformat(), "value": 3.0, "flagged": False} for i in range(days)])
    monkeypatch.setattr(ts, "chirps_climatology_total", lambda aoi, last, days: 200.0)
    monkeypatch.setattr(ts, "s1_water_per_pass", lambda aoi, area, orbit, first, last, **_: {
        "pass_dates_in_window": ["2024-05-01", "2024-05-13"], "passes_used": ["2024-05-01", "2024-05-13"], "capped": False,
        "points": [ts.s1_point({"t": "2024-05-01", "data": area, "water": 2e6}, area),
                   ts.s1_point({"t": "2024-05-13", "data": area, "water": 3e6}, area)]})


def _run(tmp_path, monkeypatch, *, trend=True):
    stack = _gee_stack(None)
    quality = {**stack.quality, "per_collection": {"sentinel_1_target": {"scenes": [{"relative_orbit": 57}]}}}
    monkeypatch.setattr(pipeline, "fetch_feature_stack", lambda *a, **k: dataclasses.replace(stack, quality=quality))
    _fake_series(monkeypatch)
    workflow = {"source": {"provider": "gee", "features": ["sar_change", "slope", "rainfall"],
                           "target_period": {"start": "2024-05-24", "end": "2024-05-26"},
                           "baseline_period": {"start": "2022-08-28", "end": "2022-09-03"}},
                "sampling": {"sample_size": 300, "min_per_class": 40, "train_fraction": 0.7, "random_seed": 3},
                "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 20},
                "context": {"trend_analysis": {"rainfall_days": 30}} if trend else {}}
    return FIRRISEngineAdapter().execute(EngineExecutionContext(
        task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), output_directory=tmp_path,
        operation="flood_mapping", products=["flood_extent", "flood_probability"], aoi_geometry=AOI,
        project_name="Rufiji flood study", aoi_name="Test floodplain", parameters={"workflow": workflow},
        gis_metadata={"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -1.6, "east": 36.6, "north": -1},
                      "spatial_resolution": {"x": 0.01, "y": 0.01, "unit": "degree"}, "producer": "NOVA GeoRisk"},
        result_version=1), lambda _: None)


def _text(path):
    return " ".join(" ".join(page.extract_text() or "" for page in PdfReader(path).pages).split())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("trend")
    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _run(directory, monkeypatch)
    finally:
        monkeypatch.undo()
    return result, directory


def test_summary_record_and_provenance(run):
    result, _ = run
    record = result.summary["trend_analysis"]
    assert record["status"] == "assessed"
    assert record["series"]["surface_water_annual"]["summary"]["kind"] == "trend"
    sar = record["series"]["sar_open_water"]
    assert sar["orbit"] == 57 and sar["summary"]["kind"] == "change"  # two passes: a change, never a trend
    assert record["rainfall_anomaly"]["anomaly_text"] == "-55.0% of the 1991–2020 mean"  # 30 × 3 mm vs 200 mm
    assert result.provenance["trend_analysis"]["s1_rule"]["threshold_db"] == -18.0
    assert "JRC/GSW1_4/YearlyHistory" in result.provenance["datasets"]


def test_files_workbook_and_report(run):
    result, directory = run
    keys = set(result.output_files)
    assert {"trend_analysis_json", "trend_surface_water_annual_csv", "trend_rainfall_daily_csv", "trend_rainfall_dekadal_csv",
            "trend_sar_open_water_csv", "trend_rainfall_anomaly_csv"} <= keys
    assert {"figure_trend_surface_water_annual_png", "figure_trend_rainfall_png", "figure_trend_sar_open_water_png"} <= keys
    sheet = load_workbook(directory / result.output_files["firris_excel_report"]["path"])["Trend analysis"]
    assert sheet.max_row > 40
    text = _text(directory / result.output_files["scientific_report_pdf"]["path"])
    assert "10. Trend analysis" in text and "SAR open water (VV < -18 dB)" in text
    assert "not a forecast" in text and "Not the FRRIS flood map and not accuracy-assessed." in text
    scope = text.split("Scope of this report")[1].split("2. Study area")[0]
    assert "Trend analysis" not in scope  # delivered, so no longer listed as not included
    assert "11. Limitations" in text


def test_a_run_without_the_option_is_unchanged(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, trend=False)
    assert "trend_analysis" not in result.summary and not any(k.startswith("trend_") for k in result.output_files)
    text = _text(tmp_path / result.output_files["scientific_report_pdf"]["path"])
    assert "Trend analysis" in text.split("Scope of this report")[1].split("2. Study area")[0]
    assert "10. Limitations" in text
