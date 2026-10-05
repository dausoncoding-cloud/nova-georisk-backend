"""Synthetic geometry, unit and completeness checks for Exposure inputs."""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError
from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform as transform_shape

from app.schemas.source_bindings import RasterGrid, SourceBoundAnalysisRequest
from app.services.source_data.exposure import _average_raster, _vector_inventory
from app.services.source_data.readiness import SourceNotReady
from tests.unit.test_firris_source_data import manifest
from tests.unit.test_source_bound_hazard import _raster


def _building_source(polygons):
    back = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    features = []
    for identifier, polygon in polygons:
        features.append({"type": "Feature", "geometry": mapping(transform_shape(back.transform, polygon)),
            "properties": {"asset_id": identifier, "building_use": "residential",
                           "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}})
    return SimpleNamespace(data=json.dumps({"type": "FeatureCollection", "features": features}).encode())


def test_vector_assets_are_counted_once_only_inside_selected_zone():
    aoi = box(0, 0, 200, 100)
    selected_cell = box(0, 0, 100, 100)
    source = _building_source([("inside", box(20, 20, 80, 80)),
                               ("boundary-touch-only", box(100, 20, 130, 80)),
                               ("outside-zone", box(140, 20, 180, 80))])
    allocation, counts, length, features = _vector_inventory(
        source, "EPSG:3857", aoi, [selected_cell], kind="buildings")
    assert allocation.tolist() == [1]
    assert counts == {"residential": 1} and length == 0
    assert [feature["properties"]["asset_id"] for feature in features] == ["inside"]
    duplicate = _building_source([("same", box(20, 20, 80, 80)),
                                   ("same", box(120, 20, 180, 80))])
    with pytest.raises(SourceNotReady, match="Duplicate"):
        _vector_inventory(duplicate, "EPSG:3857", aoi, [selected_cell], kind="buildings")


def test_density_alignment_fails_when_zone_has_unobserved_cells():
    values = np.full((10, 10), 100, dtype="float32")
    values[3, 3] = -9999
    data = _raster(values)
    source = SimpleNamespace(data=data, manifest=manifest("population_density", data,
        crs="EPSG:3857", spatial_resolution={"x": 100, "y": 100, "unit": "m"}))
    grid = RasterGrid(crs="EPSG:3857", west=300, south=300, east=700, north=700, width=4, height=4)
    with pytest.raises(SourceNotReady, match="unobserved"):
        _average_raster(source, grid, np.ones((4, 4), dtype=bool))


def test_road_on_shared_cell_edge_is_not_double_counted():
    back = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    line = {"type": "LineString", "coordinates": [list(back.transform(100, 0)),
                                                   list(back.transform(100, 100))]}
    source = SimpleNamespace(data=json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": line, "properties": {"asset_id": "edge-road",
            "road_class": "local", "observed_at": "2020-06-01T00:00:00Z", "quality_flag": "valid"}}]}).encode())
    allocation, _, length, _ = _vector_inventory(source, "EPSG:3857", box(0, 0, 200, 100),
                                                   [box(0, 0, 100, 100), box(100, 0, 200, 100)], kind="roads")
    assert 90 < length < 110
    assert allocation.sum() == pytest.approx(length)


def test_exposure_contract_requires_zone_and_rejects_bad_licence_or_units():
    fields = {"project_id": str(uuid.uuid4()), "aoi_id": str(uuid.uuid4()), "module": "exposure",
              "period": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"}}
    with pytest.raises(ValidationError, match="Exposure requires"):
        SourceBoundAnalysisRequest.model_validate(fields)
    with pytest.raises(ValidationError, match="units must be people/km2"):
        manifest("population_density", b"fixture", units="people/m2")
    with pytest.raises(ValidationError):
        manifest("population_density", b"fixture", licence={"identifier": "", "permitted_use": "", "redistribution": "allowed"})
