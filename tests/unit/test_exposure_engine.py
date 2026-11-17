"""Depth & Exposure module, Phase 2 end to end (2.4, 2.5): a FRRIS run with the hazard and the exposure switched on.

Synthetic: WorldPop is 1 person per 0.01° cell over the test AOI; Open Buildings counts are faked (one per km² of the
extent). Proves wiring, wording and files only; the real figures are checked in QA on Rufiji.
"""
import json
import uuid
import zipfile

import numpy as np
import pytest
from openpyxl import load_workbook
from pypdf import PdfReader
from rasterio.transform import Affine

from app.platform.engines.base import EngineExecutionContext
from app.platform.engines.firris import FIRRISEngineAdapter
from app.schemas.analyses import FIRRISSatelliteWorkflowConfig
from app.services.gee import firris_pipeline as pipeline
from app.services.gee import glofas_hazard as gh
from app.services.gee import open_buildings as ob
from app.services.gee import worldpop as wp
from tests.unit.test_firris_independent_accuracy import AOI, _gee_stack
from tests.unit.test_modelled_hazard_engine import _glofas


def _population(aoi, year):
    return wp.PopulationGrid(population=np.ones((60, 60), np.float32), transform=Affine(0.01, 0, 36.0, 0, -0.01, -1.0),
                             year=wp.population_year(year), requested_year=year, countries=["TZA"], images=[f"TZA_{year}"])


def _count(geometry, **kwargs):
    km2 = geometry.area * 111.0 * 111.0
    return {"0.75": {"count": int(km2), "area_m2": km2 * 50}, "0.65": {"count": int(km2 * 1.3), "area_m2": km2 * 60},
            "tiles": 1, "depth": 0, "seconds": 0.1, "method": "centroid inside the extent; exact server-side count"}


def _points(geometry, **kwargs):
    x, y = geometry.representative_point().coords[0]
    return {"status": "delivered", "reason": None,
            "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]},
                          "properties": {"area_m2": 40.0, "confidence": 0.8, "plus_code": "6G4X+XX"}}]}


def _run(tmp_path, monkeypatch, *, exposure=True, target_start="2024-05-24"):
    monkeypatch.setattr(pipeline, "fetch_feature_stack", lambda *args, **kwargs: _gee_stack(None))
    monkeypatch.setattr(gh, "acquire_glofas", _glofas)
    monkeypatch.setattr(wp, "acquire_worldpop", _population)
    monkeypatch.setattr(ob, "count_buildings", _count)
    monkeypatch.setattr(ob, "building_points", _points)
    workflow = {"source": {"provider": "gee", "features": ["sar_change", "slope", "rainfall"],
                           "target_period": {"start": target_start, "end": "2024-05-26"}},
                "sampling": {"sample_size": 300, "min_per_class": 40, "train_fraction": 0.7, "random_seed": 3},
                "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 20},
                "context": {"modelled_flood_hazard": True, "flood_exposure": exposure}}
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
    directory = tmp_path_factory.mktemp("exposure")
    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _run(directory, monkeypatch)
    finally:
        monkeypatch.undo()
    return result, directory, _text(directory / result.output_files["scientific_report_pdf"]["path"])


def test_exposure_needs_the_hazard():
    base = {"source": {"provider": "gee", "target_period": {"start": "2024-05-24", "end": "2024-05-26"},
                       "baseline_period": {"start": "2022-08-28", "end": "2022-09-03"}}}
    with pytest.raises(ValueError, match="switch on the modelled flood hazard too"):
        FIRRISSatelliteWorkflowConfig.model_validate({**base, "context": {"flood_exposure": True}})
    both = FIRRISSatelliteWorkflowConfig.model_validate({**base, "context": {"modelled_flood_hazard": True, "flood_exposure": True}})
    assert both.context.flood_exposure


def test_summary_rows_year_and_provenance(run):
    result, _, _ = run
    record = result.summary["flood_exposure"]
    assert record["status"] == "assessed"
    assert [r["extent"] for r in record["rows"]] == ["whole_area", "observed_extent", *[f"rp{p}" for p in (10, 20, 50, 75, 100, 200, 500)]]
    assert record["population"]["year"] == 2024 and record["population"]["year_status"]["status"] == "projected"
    whole = record["rows"][0]
    assert whole["people"] == pytest.approx(3600, rel=1e-3)  # 60 × 60 cells × 1 person
    observed = record["rows"][1]
    assert observed["people"] <= observed["including_permanent_water"]["people"]
    assert all(r["buildings"]["status"] == "counted" for r in record["rows"])
    assert {"WorldPop/GP/100m/R2025A/v1/pop", "GOOGLE/Research/open-buildings/v3/polygons"} <= set(result.provenance["datasets"])
    assert result.provenance["flood_exposure"]["status"] == "assessed"


def test_files_maps_workbook_and_package(run):
    result, directory, _ = run
    files = result.output_files
    for key in ("exposed_population_observed_extent", "exposed_population_rp100"):
        assert files[key]["role"] == "product" and f"{key}_map_png" in files and f"{key}_gis_layer" in files
    assert files["exposed_buildings_observed_extent"]["format"] == "geojson"
    assert "exposed_buildings_observed_extent_gpkg" in files
    table = (directory / files["flood_exposure_by_extent"]["path"]).read_text().splitlines()
    assert len(table) == 10 and "people_including_permanent_water" in table[0]
    sheets = load_workbook(directory / files["firris_excel_report"]["path"]).sheetnames
    assert {"Exposure by extent", "Exposure source"} <= set(sheets)
    with zipfile.ZipFile(directory / files["report_package"]["path"]) as package:
        names = "\n".join(package.namelist())
    for name in ("flood-exposure.json", "flood-exposure-by-extent.csv", "exposed_population_rp100.cog.tif",
                 "exposed_population_observed_extent-map.png", "exposed_buildings_observed_extent.geojson"):
        assert name in names, name


def test_report_section_13(run):
    _, _, text = run
    section = text[text.index("13. Estimated exposure (WorldPop, Open Buildings)"):text.index("Appendix A: ")]
    for part in ("Not people affected", "WorldPop R2025A, 2024", "a projection 2 years after the last census (2022)",
                 "UN World Population Prospects 2024", "area-weighted", "centroid lies inside the extent",
                 "≥ 0.75", "≥ 0.65 is shown as a sensitivity", "Exact counts, no sampling", "permanent-water cells are excluded from every extent",
                 "Observed flood candidates (this run)", "Modelled 1-in-100-year zone", "overstates exposure",
                 "doi:10.5258/SOTON/WP00839", "arXiv:2107.12283", "CC BY 4.0"):
        assert part in section, part
    main_maps = text[text.index("7. Main maps"):text.index("8. Area statistics")]
    assert "Estimated people" not in main_maps
    limitations = text[text.index("10. Limitations"):text.index("11. Provenance")]
    assert "not of people affected or damage" in limitations


def test_an_earlier_year_is_interpolated_and_stated(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, target_start="2019-04-01")
    status = result.summary["flood_exposure"]["population"]["year_status"]
    assert status["status"] == "interpolated" and "between the 2012 and 2022 censuses" in status["text"]


def test_without_exposure_nothing_is_added(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, exposure=False)
    assert "flood_exposure" not in result.summary and "modelled_flood_hazard" in result.summary
    assert not [key for key in result.output_files if "expos" in key]
