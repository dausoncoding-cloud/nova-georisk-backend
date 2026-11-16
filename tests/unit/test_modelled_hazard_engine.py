"""Depth & Exposure module, Phase 1 end to end (1.5, 1.6): a FRRIS run with the modelled hazard switched on.

Synthetic data: the GloFAS stack is a 60 × 60 grid of 0.01° over the test AOI, wet in the south (where the synthetic
flood is), deeper for longer return periods, with a strip of permanent water. Proves behaviour only.
"""
import json
import re
import uuid
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader
from rasterio.transform import Affine
import rasterio

from app.platform.engines.base import EngineExecutionContext
from app.platform.engines.firris import FIRRISEngineAdapter
from app.schemas.analyses import FIRRISSatelliteWorkflowConfig
from app.services.firris import hazard_sources as src
from app.services.gee import firris_pipeline as pipeline
from app.services.gee import glofas_hazard as gh
from tests.unit.test_firris_independent_accuracy import AOI, _gee_stack


def _glofas(aoi):
    rows, cols = np.indices((60, 60))
    depth = {}
    for i, period in enumerate(src.RETURN_PERIODS):
        wet = rows >= 30 - i  # the wet zone grows with the return period
        depth[period] = np.where(wet, 0.2 + (rows - 20) * 0.05 + i * 0.1, np.nan).astype(np.float32)
    permanent = (rows >= 55) & (cols < 10)
    return gh.GlofasStack(depth=depth, permanent_water=permanent, spurious=np.zeros((60, 60), bool),
                          covered=np.ones((60, 60), bool), transform=Affine(0.01, 0, 36.0, 0, -0.01, -1.0), crs="EPSG:4326",
                          tiles=[{"index": "ID150_N0_E30", "id": 150, "production_date": "2024-02-03"}])


def _run(tmp_path, monkeypatch, *, hazard=True, acquire=_glofas):
    monkeypatch.setattr(pipeline, "fetch_feature_stack", lambda *args, **kwargs: _gee_stack(None))
    monkeypatch.setattr(gh, "acquire_glofas", acquire)
    workflow = {"source": {"provider": "gee", "features": ["sar_change", "slope", "rainfall"]},
                "sampling": {"sample_size": 300, "min_per_class": 40, "train_fraction": 0.7, "random_seed": 3},
                "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 20}}
    if hazard:
        workflow["context"] = {"modelled_flood_hazard": True}
    return FIRRISEngineAdapter().execute(EngineExecutionContext(
        task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), output_directory=tmp_path,
        operation="flood_mapping", products=["flood_extent", "flood_probability"], aoi_geometry=AOI,
        project_name="Rufiji flood study", aoi_name="Ikwiriri floodplain", parameters={"workflow": workflow},
        gis_metadata={"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -1.6, "east": 36.6, "north": -1},
                      "spatial_resolution": {"x": 0.01, "y": 0.01, "unit": "degree"}, "producer": "NOVA GeoRisk"},
        result_version=1), lambda _: None)


def _text(path):
    return " ".join(" ".join(page.extract_text() or "" for page in PdfReader(path).pages).split())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("hazard")
    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _run(directory, monkeypatch)
    finally:
        monkeypatch.undo()
    return result, directory, _text(directory / result.output_files["scientific_report_pdf"]["path"])


def test_the_request_field_is_opt_in_and_needs_earth_engine():
    base = {"source": {"provider": "gee", "target_period": {"start": "2024-05-24", "end": "2024-05-26"},
                       "baseline_period": {"start": "2022-08-28", "end": "2022-09-03"}}}
    assert FIRRISSatelliteWorkflowConfig.model_validate(base).context.modelled_flood_hazard is False
    assert FIRRISSatelliteWorkflowConfig.model_validate({**base, "context": {"modelled_flood_hazard": True}}).context.modelled_flood_hazard
    with pytest.raises(ValueError, match="needs the Earth Engine source"):
        FIRRISSatelliteWorkflowConfig.model_validate({"source": {"provider": "prepared"}, "context": {"modelled_flood_hazard": True}})
    with pytest.raises(ValueError):
        FIRRISSatelliteWorkflowConfig.model_validate({**base, "context": {"unknown": True}})


def test_summary_record_and_provenance(run):
    result, _, _ = run
    record = result.summary["modelled_flood_hazard"]
    assert record["status"] == "assessed" and [r["return_period_years"] for r in record["return_periods"]] == list(src.RETURN_PERIODS)
    areas = [r["wet_area_km2"] for r in record["return_periods"]]
    assert areas == sorted(areas) and record["permanent_water_km2"] > 0
    assert all(r["observed_extent"]["pixels"] > 0 for r in record["return_periods"])
    assert record["licence_confirmed"] is False and record["citation"] == src.GLOFAS_CITATION
    assert result.provenance["modelled_flood_hazard"]["status"] == "assessed"
    assert src.GLOFAS_ASSET in result.provenance["datasets"]


def test_depth_layers_maps_tables_and_package(run):
    result, directory, _ = run
    files = result.output_files
    for period in src.RETURN_PERIODS:
        entry = files[f"modelled_flood_depth_rp{period}"]
        assert entry["role"] == "product" and entry["format"] == "cog"
        assert entry["layer"]["renderable"] is (period in (10, 100, 500))
        assert entry["gis_metadata"]["licence"] == src.GLOFAS_LICENCE and entry["gis_metadata"]["attribution"] == src.GLOFAS_ATTRIBUTION
        with rasterio.open(directory / entry["path"]) as raster:
            values = raster.read(1)
            assert raster.crs.to_string() == "EPSG:4326" and raster.nodata == -9999.0
            assert (values[values != -9999.0] >= 0).all() and (values == 0).any() and (values >= 0.1).any()
            assert (values[55:, :10] == -9999.0).all()  # permanent water is not in the depth layer
    for period in (10, 100, 500):
        assert f"modelled_flood_depth_rp{period}_map_png" in files and f"modelled_flood_depth_rp{period}_gis_layer" in files
    assert "modelled_flood_depth_rp20_map_png" not in files
    with zipfile.ZipFile(directory / files["modelled_flood_depth_rp100_gis_layer"]["path"]) as layer:
        readme = layer.read("README.txt").decode()
    assert "Licence: " + src.GLOFAS_LICENCE in readme and "Flood defences are not modelled" in readme
    assert "Target period" not in readme and "GloFAS" in readme
    assert files["modelled_permanent_water"]["role"] == "export"
    table = (directory / files["modelled_flood_hazard_by_return_period"]["path"]).read_text()
    assert "wet_pct_of_aoi_including_permanent_water" in table and table.count("\n") == 8
    occurrence = (directory / files["modelled_flood_hazard_occurrence"]["path"]).read_text().splitlines()
    assert occurrence[5].startswith("100,0.01,") and "0.2602996" in occurrence[5]  # 100-year flood in 30 years: 26.0%
    sheets = load_workbook(directory / files["firris_excel_report"]["path"]).sheetnames
    assert {"Modelled hazard by RP", "Hazard occurrence", "Modelled hazard source"} <= set(sheets)
    with zipfile.ZipFile(directory / files["report_package"]["path"]) as package:
        names = "\n".join(package.namelist())
    for name in ("modelled_flood_depth_rp500.cog.tif", "modelled-flood-hazard.json", "figure-modelled_hazard-aep.png",
                 "figure-modelled_hazard-depth_by_return_period.svg", "modelled_flood_depth_rp100-map.png"):
        assert name in names, name


def test_report_section_12(run):
    result, directory, text = run
    assert "12. Modelled flood hazard (GloFAS v2.1, context)" in text
    section = text[text.index("12. Modelled flood hazard"):text.index("Appendix A: ")]
    for part in ("Gumbel distribution was fitted to annual maximum river discharge", "Flood defences are not modelled",
                 "Permanent water", "excluded from the figures below", "AEP = 1/T", "P = 1 − (1 − 1/T)",
                 "context, not accuracy", "Baugh, C.", "jrc-floods-floodmapgl_rp50y-tif", "doi:10.1002/hyp.9947",
                 "doi:10.5194/nhess-17-1111-2017", "Licence under confirmation", "26.0%"):
        assert part in section, part
    assert "10.1016/j.advwatres.2016.05.002" not in text
    main_maps = text[text.index("7. Main maps"):text.index("8. Area statistics")]
    assert "Modelled flood depth" not in main_maps  # the hazard maps live in section 12
    limitations = text[text.index("10. Limitations"):text.index("11. Provenance")]
    assert "modelled river-flood hazard in section 12" in limitations
    assert "Depth, velocity, hazard, return period, exposure, vulnerability and risk are not produced" not in limitations
    docx = " ".join(p.text for p in Document(directory / result.output_files["scientific_report_word"]["path"]).paragraphs)
    assert "12. Modelled flood hazard (GloFAS v2.1, context)" in docx
    for key in ("figure_modelled_hazard_depth_by_return_period_png", "figure_modelled_hazard_aep_png"):
        assert key in result.output_files


def test_hazard_not_available_keeps_the_flood_map(tmp_path, monkeypatch):
    def outside(aoi):
        raise gh.HazardUnavailable("The area lies outside the GloFAS flood hazard maps (no tile covers it).")
    result = _run(tmp_path, monkeypatch, acquire=outside)
    record = result.summary["modelled_flood_hazard"]
    assert record["status"] == "not_available" and "outside the GloFAS" in record["reason"]
    assert "flood_extent_cog" in result.output_files and "modelled_flood_depth_rp10" not in result.output_files
    text = _text(tmp_path / result.output_files["scientific_report_pdf"]["path"])
    assert "Modelled flood hazard: not available. The area lies outside the GloFAS" in text
    assert src.GLOFAS_ASSET not in result.provenance.get("datasets", [])


def test_provider_failure_is_reported_not_raised(tmp_path, monkeypatch):
    def broken(aoi):
        raise RuntimeError("Earth Engine down")
    result = _run(tmp_path, monkeypatch, acquire=broken)
    assert result.summary["modelled_flood_hazard"]["status"] == "not_available"
    assert "could not be read from Earth Engine" in result.summary["modelled_flood_hazard"]["reason"]


def test_without_the_option_nothing_changes(tmp_path, monkeypatch, run):
    def must_not_be_called(aoi):
        raise AssertionError("GloFAS must not be read when the option is off")
    result = _run(tmp_path, monkeypatch, hazard=False, acquire=must_not_be_called)
    assert "modelled_flood_hazard" not in result.summary
    assert not [key for key in result.output_files if "modelled" in key]
    text = _text(tmp_path / result.output_files["scientific_report_pdf"]["path"])
    assert "12. Modelled flood hazard" not in text
    assert "Depth, velocity, hazard, return period, exposure, vulnerability and risk are not produced" in text
    # The flood map, its metrics and the independent accuracy are identical with and without the hazard option.
    with_hazard, hazard_dir, _ = run
    for key in ("flood_extent_cog", "flood_probability_cog"):
        assert result.output_files[key]["checksum_sha256"] == with_hazard.output_files[key]["checksum_sha256"]
    assert result.summary["validation"] == with_hazard.summary["validation"]
    assert result.summary["independent_accuracy"] == with_hazard.summary["independent_accuracy"]
