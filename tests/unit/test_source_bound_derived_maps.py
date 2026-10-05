"""M11/M12 relative-map arithmetic and real GIS artifacts; synthetic only."""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.warp import transform_bounds

from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.services.maps.export import RasterSpec, write_cog
from app.services.source_data.derived_maps import execute_derived_map, relative_quintiles
from app.services.source_data.readiness import SourceNotReady


AOI = {"type": "Polygon", "coordinates": [[[36, -2], [37, -2], [37, -1], [36, -1], [36, -2]]]}
BOUNDS = transform_bounds("EPSG:4326", "EPSG:3857", 36, -2, 37, -1)
GRID = {"crs": "EPSG:3857", "west": BOUNDS[0], "south": BOUNDS[1],
        "east": BOUNDS[2], "north": BOUNDS[3], "width": 2, "height": 2}
INDICATORS = {"rainfall_intensity", "slope", "elevation", "distance_to_river",
              "drainage_density", "flow_accumulation", "soil_permeability", "land_use_land_cover"}


def _request(module: str) -> SourceBoundAnalysisRequest:
    return SourceBoundAnalysisRequest.model_validate({
        "project_id": str(uuid.uuid4()), "aoi_id": str(uuid.uuid4()), "module": module,
        "period": {"start": "2020-06-01T00:00:00Z", "end": "2020-06-01T00:00:00Z"},
        "target_grid": GRID,
        "upstream_results": ({"hazard": str(uuid.uuid4())} if module == "flood_susceptibility"
                             else {"depth": str(uuid.uuid4()), "velocity": str(uuid.uuid4())})})


def _upstream(tmp_path: Path, name: str, values: np.ndarray, provenance: dict,
              *, vertical_datum: str | None = None):
    path = tmp_path / f"{name}.cog.tif"
    spec = RasterSpec.from_bbox(*BOUNDS, 2, 2, crs_epsg=3857)
    write_cog(str(path), np.asarray(values, dtype="float32"), spec, nodata=-9999.0)
    result = SimpleNamespace(provenance=provenance, output_files={
        "flood_depth": {"gis_metadata": {"vertical_datum": vertical_datum}}})
    return SimpleNamespace(raster_bytes=path.read_bytes(), result=result,
                           lineage=lambda: {"result_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, name)),
                                            "version": 1, "artifact_sha256": name})


def test_relative_classes_are_data_driven_and_reject_constant_or_invalid_inputs():
    legend, classes = relative_quintiles(np.asarray([0.1, 0.2, 0.3, 0.4, 0.5]))
    assert len(legend) == 5 and set(classes) == {1, 2, 3, 4, 5}
    assert all("not an absolute safety standard" in band["method"] for band in legend)
    with pytest.raises(SourceNotReady, match="varying"):
        relative_quintiles(np.ones(5))
    with pytest.raises(SourceNotReady, match="nonnegative"):
        relative_quintiles(np.asarray([-1, 0, 1]))


def test_m11_reclassifies_only_complete_approved_predictor_composite(tmp_path):
    provenance = {"indicator_units": {name: "reviewed-unit" for name in INDICATORS},
                  "indicator_directions": {name: "benefit" for name in INDICATORS},
                  "weights": {name: 1 / 8 for name in INDICATORS},
                  "normalization_ranges": {name: {"raw_min": 0, "raw_max": 1} for name in INDICATORS},
                  "source_bindings": {"rainfall": {"dataset_id": "reviewed-synthetic"}}}
    upstream = _upstream(tmp_path, "hazard", [[0.1, 0.2], [0.3, 0.4]], provenance)
    request = _request("flood_susceptibility")
    bindings = SimpleNamespace(request=request, sources={}, upstream={"hazard": upstream})
    output = execute_derived_map(bindings, AOI, tmp_path / "m11", 1, task_id=str(uuid.uuid4()))
    assert output.result_type == "source_bound_flood_susceptibility"
    assert set(output.provenance["predictor_inventory"]) == INDICATORS
    assert "not an independently fitted" in output.provenance["validation_limitations"][0]
    with rasterio.open(tmp_path / "m11" / "flood_susceptibility.cog.tif") as raster:
        assert raster.is_tiled and raster.crs.to_string() == "EPSG:3857"
        np.testing.assert_allclose(raster.read(1, masked=True).compressed(), [0.1, 0.2, 0.3, 0.4])
    assert all(key in output.output_files for key in
               ("flood_susceptibility", "flood_susceptibility_preview",
                "flood_susceptibility_csv", "flood_susceptibility_excel",
                "flood_susceptibility_pdf", "report_package"))
    provenance["weights"].pop("slope")
    with pytest.raises(SourceNotReady, match="inventory"):
        execute_derived_map(bindings, AOI, tmp_path / "rejected", 1, task_id=str(uuid.uuid4()))


def test_m12_zones_use_depth_times_velocity_without_probability_substitution(tmp_path):
    depth = _upstream(tmp_path, "depth", [[1, 2], [3, 4]], {}, vertical_datum="reviewed-MSL")
    velocity = _upstream(tmp_path, "velocity", [[2, 2], [2, 2]], {})
    request = _request("flood_hazard_zonation")
    output = execute_derived_map(
        SimpleNamespace(request=request, sources={}, upstream={"depth": depth, "velocity": velocity}),
        AOI, tmp_path / "m12", 1, task_id=str(uuid.uuid4()))
    assert output.provenance["formula_implementation"] == "app.services.maps.flood_products.compute_hazard_index"
    assert set(output.provenance["upstream_results"]) == {"depth", "velocity"}
    metadata = output.output_files["flood_hazard_zonation"]["gis_metadata"]
    assert metadata["vertical_datum"] == "reviewed-MSL"
    assert metadata["zone_break_policy"] == "empirical AOI quintiles of source index; no fixed safety thresholds"
    with rasterio.open(tmp_path / "m12" / "flood_hazard_zonation.cog.tif") as raster:
        assert raster.is_tiled and raster.nodata == -9999.0
        np.testing.assert_array_equal(raster.read(1, masked=True).compressed(), [1, 2, 4, 5])
    assert all(key in output.output_files for key in
               ("flood_hazard_zonation_preview", "flood_hazard_zonation_csv",
                "flood_hazard_zonation_excel", "flood_hazard_zonation_pdf", "report_package"))
