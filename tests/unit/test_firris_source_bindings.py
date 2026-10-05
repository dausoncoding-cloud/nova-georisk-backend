"""Synthetic sources exercise binding/alignment mechanics, not model accuracy."""
from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.schemas.source_bindings import RasterGrid, SourceBoundAnalysisRequest
from app.services.source_data.alignment import align_raster_bundle, align_raster_source
from app.services.source_data.bindings import MODULE_RESULT_ROLES, MODULE_SOURCE_ROLES, ResolvedBindings, binding_contract
from app.services.source_data.catalogue import get_profile
from app.services.source_data.readiness import ReadySource, SourceNotReady
from app.services.source_data.science import execute_survey_module
from tests.unit.test_firris_source_data import manifest


AOI = {"type": "Polygon", "coordinates": [[[36, -1], [36.2, -1], [36.2, -1.1], [36, -1.1], [36, -1]]]}


def _source(category, data, **manifest_overrides):
    return ReadySource(SimpleNamespace(id=uuid.uuid4(), created_at=None), manifest(category, data, **manifest_overrides), data,
                       {"analysis_ready": True, "evidence_refs": ["synthetic test only"]})


def _boundary_source():
    features = []
    for unit, x in (("a", 36), ("b", 36.1)):
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[x, -1], [x + 0.1, -1], [x + 0.1, -1.1], [x, -1.1], [x, -1]]]},
                         "properties": {"spatial_unit_id": unit, "name": unit, "level": "test", "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}})
    data = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    return _source("administrative_boundaries", data, source_id="reviewed-boundaries")


def _indicator_source(category):
    profile = get_profile(category)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(profile["required_fields"]))
    writer.writeheader()
    for unit, scale in (("a", 1), ("b", 2)):
        for index, key in enumerate(profile["required_indicators"]):
            writer.writerow({"spatial_unit_id": unit, "indicator_key": key, "value": scale * (index + 1), "unit": "test-unit", "observed_at": "2020-06-01T00:00:00Z", "sample_n": 10, "quality_flag": "valid"})
    return _source(category, stream.getvalue().encode(), source_id=f"{category}-reviewed", spatial_unit_reference="reviewed-boundaries",
                   indicator_units={key: "test-unit" for key in profile["required_indicators"]})


def _request(module, sources):
    return SourceBoundAnalysisRequest(
        project_id=uuid.uuid4(), aoi_id=uuid.uuid4(), module=module,
        sources={role: source.dataset.id for role, source in sources.items()},
        period={"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"},
    )


def test_explicit_module_contracts_do_not_substitute_risk_formula():
    contract = binding_contract()
    assert set(contract) == {"hazard", "exposure", "vulnerability", "insecurity", "risk", "resilience",
                             "flood_depth", "flood_velocity", "flood_hazard_product",
                             "flood_aep", "flood_return_period", "flood_duration",
                             "flood_susceptibility", "flood_hazard_zonation", "satellite_preprocessing"}
    assert contract["satellite_preprocessing"]["source_roles"] == {}
    assert contract["satellite_preprocessing"]["optional_source_roles"] == {
        "climate": "rainfall_stations", "soil": "soil_permeability", "population": "population_density",
        "roads": "roads", "rivers": "river_drainage_network", "land_cover": "land_cover", "terrain": "terrain_dem"}
    assert contract["satellite_preprocessing"]["upstream_result_roles"] == {}
    assert contract["flood_depth"]["source_roles"] == {"water_surface": "water_surface_elevation", "terrain": "terrain_dem"}
    assert contract["flood_velocity"]["source_roles"] == {"model_velocity": "hydraulic_model_velocity"}
    assert contract["flood_hazard_product"]["upstream_result_roles"] == {
        "depth": "source_bound_flood_depth", "velocity": "source_bound_flood_velocity"}
    assert "year_<YYYY>" in contract["flood_aep"]["source_role_pattern"]
    assert "slice_<zero-based index>" in contract["flood_duration"]["source_role_pattern"]
    assert contract["flood_return_period"]["upstream_result_roles"] == {"aep": "source_bound_flood_aep"}
    assert contract["flood_susceptibility"]["upstream_result_roles"] == {"hazard": "source_bound_hazard"}
    assert contract["flood_hazard_zonation"]["upstream_result_roles"] == {
        "depth": "source_bound_flood_depth", "velocity": "source_bound_flood_velocity"}
    assert set(MODULE_RESULT_ROLES["risk"]) == {"hazard", "exposure", "insecurity"}
    assert MODULE_RESULT_ROLES["insecurity"] == {"vulnerability": "source_bound_vulnerability"}
    assert set(MODULE_SOURCE_ROLES["insecurity"]) == {"capacity", "boundaries"}
    assert "vulnerability" not in MODULE_RESULT_ROLES["risk"]
    assert contract["risk"]["executable"] is True
    assert contract["risk"]["source_roles"] == {}
    assert MODULE_SOURCE_ROLES["vulnerability"]["indicators"] == "vulnerability_indicators"


@pytest.mark.parametrize("module", ["vulnerability", "resilience"])
def test_approved_survey_sources_feed_existing_formulas_with_lineage(module, tmp_path):
    sources = {"boundaries": _boundary_source()}
    if module == "vulnerability":
        sources["indicators"] = _indicator_source("vulnerability_indicators")
    if module == "resilience":
        sources["capacity"] = _indicator_source("community_capacity_indicators")
    output = execute_survey_module(ResolvedBindings(_request(module, sources), sources, {}), AOI, tmp_path, 1)
    assert output.result_type == f"source_bound_{module}"
    assert len(output.summary["scores_by_spatial_unit"]) == 2
    assert output.provenance["weights"][module]
    assert {entry["sha256"] for entry in output.provenance["source_bindings"].values()} == {source.manifest.sha256 for source in sources.values()}
    assert (tmp_path / f"source-bound-{module}.geojson").is_file()


def test_raster_alignment_requires_full_aoi_coverage_and_no_upsampling():
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=2, height=2, count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(36, -1, 0.1, 0.1), nodata=-9999) as dst:
            dst.write(np.array([[1, 2], [3, 4]], dtype="float32"), 1)
        data = mem.read()
    source = _source("terrain_dem", data)
    grid = RasterGrid(crs="EPSG:4326", west=36, south=-1.2, east=36.2, north=-1, width=2, height=2)
    full_aoi = {"type": "Polygon", "coordinates": [[[36, -1], [36.2, -1], [36.2, -1.2], [36, -1.2], [36, -1]]]}
    aligned, mask, record = align_raster_source(source, grid, full_aoi)
    assert mask.all() and np.isfinite(aligned).all()
    assert record["resampling"] == "nearest"
    with pytest.raises(SourceNotReady, match="upsample"):
        align_raster_source(source, RasterGrid(crs="EPSG:4326", west=36, south=-1.2, east=36.2, north=-1, width=4, height=4), full_aoi)
    with pytest.raises(SourceNotReady, match="cover"):
        expanded_aoi = {"type": "Polygon", "coordinates": [[[35.9, -1], [36.2, -1], [36.2, -1.2], [35.9, -1.2], [35.9, -1]]]}
        align_raster_source(source, RasterGrid(crs="EPSG:4326", west=35.9, south=-1.2, east=36.2, north=-1, width=3, height=2), expanded_aoi)


def test_raster_reprojection_is_explicit_and_vertical_datum_conflict_fails():
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=2, height=2, count=1, dtype="float32", crs="EPSG:3857", transform=from_origin(0, 200, 100, 100), nodata=-9999) as dst:
            dst.write(np.array([[1, 2], [3, 4]], dtype="float32"), 1)
        data = mem.read()
    first = _source("terrain_dem", data, crs="EPSG:3857", spatial_resolution={"x": 100, "y": 100, "unit": "m"}, vertical_datum="EGM2008")
    second = _source("water_surface_elevation", data, crs="EPSG:3857", spatial_resolution={"x": 100, "y": 100, "unit": "m"}, vertical_datum="NAVD88")
    side = 0.0017966
    aoi = {"type": "Polygon", "coordinates": [[[0, 0], [side, 0], [side, side], [0, side], [0, 0]]]}
    grid = RasterGrid(crs="EPSG:4326", west=0, south=0, east=side, north=side, width=2, height=2)
    values, mask, record = align_raster_source(first, grid, aoi)
    assert mask.all() and np.isfinite(values).all()
    assert record["source_crs"] == "EPSG:3857" and record["target_crs"] == "EPSG:4326"
    with pytest.raises(SourceNotReady, match="vertical datums"):
        align_raster_bundle({"terrain": first, "water_surface": second}, grid, aoi)
