"""Synthetic records test ingestion mechanics, never scientific accuracy."""
from __future__ import annotations

import hashlib
import io
import json
import uuid

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.schemas.source_data import SourceDatasetManifest
from app.services.source_data.catalogue import get_catalogue, get_profile
from app.services.source_data.validators import SourceDataValidationError, validate_source_data


def manifest(category: str, data: bytes, **overrides) -> SourceDatasetManifest:
    profile = get_profile(category)
    fields = {
        "project_id": str(uuid.uuid4()), "category": category, "source_id": "fixture-only",
        "crs": "EPSG:4326", "vertical_datum": "EGM2008" if profile["vertical_datum"] == "required" else None,
        "units": profile["unit"], "temporal_coverage": {"start": "2020-01-01T00:00:00Z", "end": "2020-12-31T23:59:59Z"},
        "geographic_coverage": {"west": -180, "south": -90, "east": 180, "north": 90},
        "spatial_resolution": {"x": 0.1, "y": 0.1, "unit": "degree"} if profile["format"] == "geotiff" else None,
        "positional_uncertainty_m": 10 if profile["format"] == "geojson" or "longitude_latitude_columns" in profile["geometry"] else None,
        "spatial_unit_reference": "approved-boundary-fixture" if "spatial_unit_id_join" in profile["geometry"] else None,
        "quality_assessment": {"method": "independent source review", "assessed_at": "2021-01-01T00:00:00Z", "assessor": "fixture assessor", "status": "passed"},
        "licence": {"identifier": "fixture-licence", "permitted_use": "test ingestion", "redistribution": "restricted"},
        "provenance": {"producer": "fixture producer", "custodian": "fixture custodian", "source_uri": "fixture:synthetic", "acquisition_method": "synthetic unit fixture"},
        "uncertainty": {"measure": "synthetic positional error", "value": 10, "unit": "m"},
        "sha256": hashlib.sha256(data).hexdigest(), "nodata": -9999 if profile["format"] == "geotiff" else None,
        "indicator_units": {key: "declared-unit" for key in profile.get("required_indicators", [])} or None,
        "indicator_directions": {key: "benefit" for key in profile.get("required_indicators", [])} if category in {"vulnerability_indicators", "community_capacity_indicators"} else None,
        "indicator_scale_descriptions": {key: "Higher fixture score represents more of this measured property" for key in profile.get("required_indicators", [])} if category in {"vulnerability_indicators", "community_capacity_indicators"} else None,
        "missing_value_policy": "reject" if category in {"vulnerability_indicators", "community_capacity_indicators"} else None,
        "class_scheme": {"1": "class one"} if category == "land_cover" else None,
        "hydraulic_model_run_id": "synthetic-model-run" if category == "hydraulic_model_velocity" else None,
        "hydraulic_model_validation_reference": "fixture-review-record" if category == "hydraulic_model_velocity" else None,
        "observation_year": 2020 if category == "annual_inundation_observation" else None,
        "event_definition": "annual maximum inundation above fixed fixture threshold" if category == "annual_inundation_observation" else None,
        "predictor_definitions": {"fixture": {"role": "response", "family": "hydrology", "unit": "declared-unit", "definition": "Synthetic observed response", "evidence_ref": "fixture:synthetic"},
                                  "predictor": {"role": "predictor", "family": "climate", "unit": "declared-unit", "definition": "Synthetic observed predictor", "evidence_ref": "fixture:synthetic"}} if category == "flood_predictor_observations" else None,
        "predictor_catalogue_reference": "fixture:synthetic" if category == "flood_predictor_observations" else None,
        "soil_scoring_policy": {"classes": {str(i): {"label": f"Synthetic soil class {i}", "score": i} for i in range(1, 6)}, "specification_reference": "fixture:synthetic", "score_definition": "Synthetic lookup scores; no scientific calibration", "score_units": "synthetic_score"} if category == "soil_texture_classes" else None,
    }
    fields.update(overrides)
    return SourceDatasetManifest.model_validate(fields)


def test_catalogue_has_explicit_contract_for_every_handoff_category():
    catalogue = get_catalogue()
    assert len(catalogue["profiles"]) == 28
    assert get_profile("hydraulic_model_velocity")["unit"] == "m/s"
    assert get_profile("annual_inundation_observation")["unit"] == "annual_exceedance_0_1"
    assert all({"format", "geometry", "crs", "vertical_datum", "unit", "temporal_mode", "spatial_resolution", "required_fields", "downstream_rows"} <= set(p) for p in catalogue["profiles"].values())


def test_manifest_requires_vertical_datum_licence_uncertainty_and_quality():
    base = manifest("river_stage_stations", b"fixture")
    for key, invalid in (("vertical_datum", None), ("licence", None), ("uncertainty", None), ("quality_assessment", None)):
        with pytest.raises(ValidationError):
            SourceDatasetManifest.model_validate({**base.model_dump(), key: invalid})
    with pytest.raises(ValidationError):
        manifest("river_stage_stations", b"fixture", crs="EPSG:3857")
    with pytest.raises(ValidationError, match="positional uncertainty"):
        manifest("rainfall_stations", b"fixture", positional_uncertainty_m=None)
    with pytest.raises(ValidationError, match="boundary source reference"):
        manifest("vulnerability_indicators", b"fixture", spatial_unit_reference=None)


def test_csv_station_valid_and_bad_quality_or_time_rejected():
    header = "station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag\n"
    good = (header + "g1,36,-1,2020-06-01T00:00:00Z,12,valid\n").encode()
    report = validate_source_data(manifest("rainfall_stations", good), good, "rain.csv")
    assert report.record_count == 1 and report.analysis_ready is False
    for row in ("g1,36,-1,2020-06-01T00:00:00Z,12,suspect\n", "g1,36,-1,2022-06-01T00:00:00Z,12,valid\n", "g1,36,-1,2020-06-01T00:00:00Z,-1,valid\n"):
        data = (header + row).encode()
        with pytest.raises(SourceDataValidationError):
            validate_source_data(manifest("rainfall_stations", data), data, "rain.csv")


def test_checksum_and_undeclared_fields_fail_closed():
    data = b"station_id,longitude,latitude,observed_at,rainfall_mm,quality_flag,email\ng1,36,-1,2020-06-01T00:00:00Z,12,valid,user@example.com\n"
    with pytest.raises(SourceDataValidationError, match="fields"):
        validate_source_data(manifest("rainfall_stations", data), data, "rain.csv")
    with pytest.raises(SourceDataValidationError, match="checksum"):
        validate_source_data(manifest("rainfall_stations", data), b"changed", "rain.csv")


def test_geojson_geometry_and_qa_are_checked():
    feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [36, -1]}, "properties": {"asset_id": "h1", "asset_type": "hospital", "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}}
    data = json.dumps({"type": "FeatureCollection", "features": [feature]}).encode()
    assert validate_source_data(manifest("critical_infrastructure", data), data, "assets.geojson").bounds == [36, -1, 36, -1]
    feature["properties"]["quality_flag"] = "missing"
    bad = json.dumps({"type": "FeatureCollection", "features": [feature]}).encode()
    with pytest.raises(SourceDataValidationError):
        validate_source_data(manifest("critical_infrastructure", bad), bad, "assets.geojson")


def test_indicator_rows_require_complete_declared_set():
    data = b"spatial_unit_id,indicator_key,value,unit,observed_at,sample_n,quality_flag\na,population_density,5,declared-unit,2020-06-01T00:00:00Z,10,valid\n"
    with pytest.raises(SourceDataValidationError, match="Incomplete indicator"):
        validate_source_data(manifest("vulnerability_indicators", data), data, "survey.csv")


def test_geotiff_crs_resolution_nodata_and_values():
    def raster(value):
        with MemoryFile() as mem:
            with mem.open(driver="GTiff", width=2, height=2, count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(36, 0, 0.1, 0.1), nodata=-9999) as dst:
                dst.write(np.full((2, 2), value, dtype="float32"), 1)
            return mem.read()
    good = raster(0.5)
    assert validate_source_data(manifest("cropland_fraction", good), good, "crop.tif").record_count == 4
    bad = raster(1.5)
    with pytest.raises(SourceDataValidationError, match="fraction"):
        validate_source_data(manifest("cropland_fraction", bad), bad, "crop.tif")
    with pytest.raises(ValidationError, match="nodata"):
        manifest("cropland_fraction", good, nodata=None)
    wrong = manifest("cropland_fraction", good, crs="EPSG:3857")
    with pytest.raises(SourceDataValidationError, match="CRS"):
        validate_source_data(wrong, good, "crop.tif")


@pytest.mark.parametrize("category", sorted(get_catalogue()["profiles"]))
def test_every_catalogue_category_has_a_validatable_structural_fixture(category):
    profile = get_profile(category)
    if profile["format"] == "geotiff":
        with MemoryFile() as mem:
            with mem.open(driver="GTiff", width=1, height=1, count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(36, 0, 0.1, 0.1), nodata=-9999) as dst:
                dst.write(np.array([[1]], dtype="float32"), 1)
            data, filename = mem.read(), "source.tif"
    else:
        fields = profile["required_fields"]
        def value(key, kind):
            if kind == "datetime":
                return "2020-06-01T00:00:00Z"
            if kind == "quality_flag":
                return "valid"
            if kind in {"longitude", "latitude"}:
                return 36 if kind == "longitude" else -1
            if kind in {"number", "nonnegative_number", "positive_number", "positive_integer"}:
                return 1
            if key == "unit":
                return "declared-unit"
            return "fixture"
        rows = []
        for indicator in profile.get("required_indicators", [None]):
            row = {key: value(key, kind) for key, kind in fields.items()}
            if indicator:
                row["indicator_key"] = indicator
            rows.append(row)
        if profile["format"] == "csv":
            stream = io.StringIO()
            import csv
            writer = csv.DictWriter(stream, fieldnames=list(fields))
            writer.writeheader()
            writer.writerows(rows)
            data, filename = stream.getvalue().encode(), "source.csv"
        else:
            geometry_type = profile["geometry"][0]
            coordinates = {
                "Point": [36, -1],
                "LineString": [[36, -1], [36.1, -1]],
                "Polygon": [[[36, -1], [36.1, -1], [36.1, -1.1], [36, -1]]],
            }[geometry_type]
            data = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": geometry_type, "coordinates": coordinates}, "properties": row} for row in rows]}).encode()
            filename = "source.geojson"
    overrides = ({"temporal_coverage": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"}}
                 if category == "inundation_time_slice" else
                 {"temporal_coverage": {"start": "2020-01-01T00:00:00Z", "end": "2020-12-31T23:59:59Z"}}
                 if category == "annual_inundation_observation" else {})
    report = validate_source_data(manifest(category, data, **overrides), data, filename)
    assert report.record_count >= 1
    assert report.analysis_ready is False
