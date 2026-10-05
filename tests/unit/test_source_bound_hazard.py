"""Synthetic engineering tests of the source-bound Hazard adapter, not field validation."""
from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import rasterio
from pydantic import ValidationError
from PIL import Image
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.services.firas.hazard import compute_hazard_index
from app.services.source_data.bindings import ResolvedBindings, resolve_bindings
from app.services.source_data.hazard import _LAND_COVER_NAMES, execute_hazard_module
from app.services.source_data.readiness import ReadySource, SourceNotReady
from tests.unit.test_firris_source_data import manifest


def _raster(values):
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=10, height=10, count=1, dtype="float32",
                         crs="EPSG:3857", transform=from_origin(0, 1000, 100, 100), nodata=-9999) as dst:
            dst.write(np.asarray(values, dtype="float32"), 1)
        return memory.read()


def _geojson(lines):
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": line},
         "properties": {"feature_id": str(index), "network_type": "river",
                        "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}}
        for index, line in enumerate(lines)
    ]}).encode()


def _source(category, data, **overrides):
    raster = category in {"terrain_dem", "soil_permeability", "land_cover"}
    fields = {"crs": "EPSG:3857", "spatial_resolution": {"x": 100, "y": 100, "unit": "m"}} if raster else {}
    fields.update(overrides)
    evidence = {"analysis_ready": True, "evidence_refs": ["reviewed-hydrology-coverage"],
                "checks": {"hydrologic_coverage_verified": True, "dem_conditioning_verified": True}}
    return ReadySource(SimpleNamespace(id=uuid.uuid4(), created_at=None),
                       manifest(category, data, **fields), data, evidence)


def _fixture():
    to_wgs = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    west, south = to_wgs.transform(300, 300)
    east, north = to_wgs.transform(700, 700)
    aoi = {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north],
                                                    [west, north], [west, south]]]}
    def line(x):
        return [list(to_wgs.transform(x, 100)), list(to_wgs.transform(x, 900))]
    stations = [("a", 100, 100, 10), ("b", 900, 100, 25), ("c", 100, 900, 40), ("d", 900, 900, 15)]
    rainfall = "station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\n"
    for name, x, y, mm in stations:
        lon, lat = to_wgs.transform(x, y)
        rainfall += f"{name},{lon},{lat},2020-06-01T00:00:00Z,{mm},valid\n"
    dem = 500 - np.add.outer(np.arange(10) * 4, np.arange(10) * 2)
    land = np.tile(np.array([10, 20, 30, 40, 50, 60, 70, 80, 90, 95]), (10, 1))
    sources = {
        "rainfall": _source("rainfall_stations", rainfall.encode(), observation_interval_hours=1),
        "terrain": _source("terrain_dem", _raster(dem)),
        "river_network": _source("river_drainage_network", _geojson([line(150), line(800)])),
        "land_cover": _source("land_cover", _raster(land), land_cover_scheme="esa_worldcover",
                              class_scheme={str(code): _LAND_COVER_NAMES["esa_worldcover"][int(code)]
                                            for code in np.unique(land)}),
        "soil": _source("soil_permeability", _raster(np.add.outer(np.arange(10), np.arange(10)) + 1)),
    }
    request = SourceBoundAnalysisRequest(
        project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), module="hazard",
        sources={role: source.dataset.id for role, source in sources.items()},
        period={"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"},
        target_grid={"crs": "EPSG:3857", "west": 300, "south": 300, "east": 700, "north": 700,
                     "width": 4, "height": 4}, hazard_options={"drainage_window_m": 300},
    )
    return request, aoi, sources


def test_approved_hazard_sources_execute_formula_and_write_valid_gis_outputs(tmp_path):
    request, aoi, sources = _fixture()
    output = execute_hazard_module(ResolvedBindings(request, sources, {}), aoi, tmp_path, 2, task_id="test-task")
    assert output.result_type == "source_bound_hazard"
    assert set(output.provenance["weights"]) == set(output.provenance["indicator_units"])
    assert sum(output.provenance["weights"].values()) == pytest.approx(1)
    assert output.provenance["source_bindings"]["rainfall"]["sha256"] == hashlib.sha256(sources["rainfall"].data).hexdigest()
    assert output.provenance["processing"]["terrain"]["method"].startswith("finite-difference")
    assert output.provenance["processing"]["river_network"]["drainage_window_m"] == 300
    assert output.provenance["normalization_ranges"]["rainfall_intensity"]["raw_unit"] == "mm/h"
    with rasterio.open(tmp_path / output.output_files["flood_hazard"]["path"]) as raster:
        actual = raster.read(1)
        assert raster.driver == "GTiff" and raster.is_tiled
        assert raster.crs.to_string() == "EPSG:3857" and raster.nodata == -9999
        assert actual.shape == (4, 4) and np.isfinite(actual).all()
        assert actual.min() >= 0 and actual.max() <= 1
    raw = pd.DataFrame({key: [] for key in output.provenance["indicator_units"]})
    for key in raw:
        with rasterio.open(tmp_path / output.output_files[f"indicator_{key}"]["path"]) as raster:
            raw[key] = raster.read(1).ravel().astype(float)
    expected = sum(output.provenance["weights"][key] * raw[key].to_numpy() for key in raw)
    assert np.allclose(actual.ravel(), expected, atol=1e-6)
    assert (tmp_path / output.output_files["flood_hazard_preview"]["path"]).is_file()
    preview = np.asarray(Image.open(tmp_path / output.output_files["flood_hazard_preview"]["path"]))
    assert preview.shape == (4, 4, 4) and np.all(preview[..., 3] == 255)
    assert output.output_files["flood_hazard"]["gis_metadata"]["legend"][0]["label"] == "Very Low"
    assert (tmp_path / output.output_files["report_package"]["path"]).is_file()
    with zipfile.ZipFile(tmp_path / output.output_files["report_package"]["path"]) as package:
        names = set(package.namelist())
        assert {"analysis-summary.json", "result-metadata.json", "provenance.json"}.issubset(names)
        assert "products/flood-hazard-index.cog.tif" in names


def test_hazard_preflight_rejects_unreviewed_dem_bad_units_crs_and_time(monkeypatch):
    request, aoi, sources = _fixture()
    by_id = {source.dataset.id: source for source in sources.values()}
    monkeypatch.setattr("app.services.source_data.bindings.load_registered_source",
                        lambda _db, dataset_id, _project_id, **_kw: by_id[dataset_id])
    assert resolve_bindings(None, request, aoi_geometry=aoi).sources == sources
    unreviewed = _source("terrain_dem", sources["terrain"].data)
    unreviewed.evidence["checks"]["hydrologic_coverage_verified"] = False
    by_id[sources["terrain"].dataset.id] = unreviewed
    with pytest.raises(SourceNotReady, match="upstream hydrologic coverage"):
        resolve_bindings(None, request, aoi_geometry=aoi)
    by_id[sources["terrain"].dataset.id] = sources["terrain"]
    wrong_time = request.model_copy(update={"period": request.period.model_copy(update={"end": request.period.end.replace(year=2022)})})
    with pytest.raises(SourceNotReady, match="period"):
        resolve_bindings(None, wrong_time, aoi_geometry=aoi)
    wrong_crs = request.model_copy(update={"target_grid": request.target_grid.model_copy(update={"crs": "EPSG:4326"})})
    with pytest.raises(SourceNotReady):
        resolve_bindings(None, wrong_crs, aoi_geometry=aoi)
    wrong_units = _source("rainfall_stations", sources["rainfall"].data, observation_interval_hours=None)
    by_id[sources["rainfall"].dataset.id] = wrong_units
    with pytest.raises(SourceNotReady, match="observation interval"):
        resolve_bindings(None, request, aoi_geometry=aoi)


def test_hazard_rejects_incomplete_rainfall_schedule(tmp_path):
    request, aoi, sources = _fixture()
    rainfall = sources["rainfall"].data.decode().splitlines()
    data = ("\n".join(rainfall[:-2]) + "\n").encode()
    sources["rainfall"] = _source("rainfall_stations", data, observation_interval_hours=1)
    with pytest.raises(SourceNotReady, match="three observed stations"):
        execute_hazard_module(ResolvedBindings(request, sources, {}), aoi, tmp_path, 1)


def test_hazard_rejects_unit_or_land_cover_taxonomy_mismatch(tmp_path):
    request, aoi, sources = _fixture()
    with pytest.raises(ValidationError, match="units must be mm"):
        manifest("rainfall_stations", sources["rainfall"].data, units="mm/h")
    land = sources["land_cover"]
    wrong_classes = {**land.manifest.class_scheme, "10": "Built-up"}
    sources["land_cover"] = _source("land_cover", land.data,
        land_cover_scheme="esa_worldcover", class_scheme=wrong_classes)
    with pytest.raises(SourceNotReady, match="class labels"):
        execute_hazard_module(ResolvedBindings(request, sources, {}), aoi, tmp_path, 1)
