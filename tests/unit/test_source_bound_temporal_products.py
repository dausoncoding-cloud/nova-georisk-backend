"""Synthetic AEP/duration arithmetic and temporal fail-closed checks."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.schemas.source_data import SourceDatasetManifest
from app.services.maps.flood_products import probability_to_return_period
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.temporal_products import compute_duration_hours, compute_empirical_aep, execute_temporal_product
from app.services.source_data.temporal_results import load_aep_result
from app.services.source_data.temporal_sources import validate_annual_sources, validate_duration_sources
from tests.unit.test_firris_source_data import manifest


_AOI = {"type": "Polygon", "coordinates": [[[36, -2], [37, -2], [37, -1], [36, -1], [36, -2]]]}
_BOUNDS = transform_bounds("EPSG:4326", "EPSG:3857", 36, -2, 37, -1)
_GRID = {"crs": "EPSG:3857", "west": _BOUNDS[0], "south": _BOUNDS[1],
         "east": _BOUNDS[2], "north": _BOUNDS[3], "width": 2, "height": 2}


def _data(values):
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=2, height=2, count=1, dtype="float32",
                         crs="EPSG:3857", transform=from_bounds(*_BOUNDS, 2, 2), nodata=-9999) as raster:
            raster.write(np.asarray(values, dtype="float32"), 1)
        return memory.read()


def _request(module, start, end, *, cadence=None):
    return SourceBoundAnalysisRequest.model_validate({
        "project_id": str(uuid.uuid4()), "aoi_id": str(uuid.uuid4()), "module": module,
        "period": {"start": start, "end": end}, "target_grid": _GRID,
        **({"duration_options": {"temporal_resolution_hours": cadence, "gap_policy": "reject"}}
           if cadence else {})})


def _source(category, timestamp=None, year=None, values=None, reviewed=True):
    data = _data(np.zeros((2, 2)) if values is None else values)
    profile_manifest = manifest(category, data,
        crs="EPSG:3857", spatial_resolution={"x": (_BOUNDS[2] - _BOUNDS[0]) / 2,
                                              "y": (_BOUNDS[3] - _BOUNDS[1]) / 2, "unit": "m"},
        temporal_coverage=({"start": f"{year}-01-01T00:00:00Z", "end": f"{year}-12-31T23:59:59Z"}
                           if year else {"start": timestamp, "end": timestamp}),
        observation_year=year,
        event_definition="annual maximum inundation exceeds fixed reviewed cell threshold" if year else None)
    return SimpleNamespace(data=data, manifest=profile_manifest,
                           evidence={"checks": {"annual_record_complete_verified": reviewed}})


def test_empirical_aep_and_return_period_use_annual_events_not_rf_score():
    mask = np.ones((2, 2), dtype=bool)
    annual = [np.array([[int(index < 2), int(index < 5)], [1, 0]], dtype="uint8")
              for index in range(10)]
    aep = compute_empirical_aep(annual, mask)
    np.testing.assert_allclose(aep, [0.2, 0.5, 1.0, 0.0])
    assert probability_to_return_period(float(aep[0])) == pytest.approx(5)
    assert probability_to_return_period(float(aep[1])) == pytest.approx(2)
    with pytest.raises(ValueError):
        probability_to_return_period(float(aep[-1]))
    with pytest.raises(SourceNotReady, match="ten"):
        compute_empirical_aep(annual[:-1], mask)
    with pytest.raises(SourceNotReady, match="binary"):
        compute_empirical_aep(annual[:-1] + [np.full((2, 2), 0.8)], mask)


def test_annual_record_rejects_missing_year_review_and_changed_definition():
    request = _request("flood_aep", "2010-01-01T00:00:00Z", "2019-12-31T23:59:59Z")
    sources = {f"year_{year}": _source("annual_inundation_observation", year=year)
               for year in range(2010, 2020)}
    arrays, mask, evidence = validate_annual_sources(request, sources, _AOI)
    assert len(arrays) == evidence["record_length_years"] == 10 and mask.any()
    with pytest.raises(SourceNotReady, match="ten"):
        validate_annual_sources(request, {k: v for k, v in sources.items() if k != "year_2019"}, _AOI)
    sources["year_2019"].evidence["checks"]["annual_record_complete_verified"] = False
    with pytest.raises(SourceNotReady, match="completeness"):
        validate_annual_sources(request, sources, _AOI)
    sources["year_2019"].evidence["checks"]["annual_record_complete_verified"] = True
    sources["year_2019"].manifest = sources["year_2019"].manifest.model_copy(
        update={"event_definition": "different annual maximum exceedance threshold"})
    with pytest.raises(SourceNotReady, match="definition"):
        validate_annual_sources(request, sources, _AOI)


def test_rf_result_type_cannot_satisfy_aep_dependency():
    request = _request("flood_return_period", "2010-01-01T00:00:00Z", "2019-12-31T23:59:59Z")
    rf_id = uuid.uuid4()
    request.upstream_results["aep"] = rf_id
    rf_result = SimpleNamespace(id=rf_id, project_id=request.project_id, aoi_id=request.aoi_id,
                                engine_key="firris", result_type="flood_mapping")
    db = SimpleNamespace(get=lambda model, key: rf_result)
    with pytest.raises(SourceNotReady, match="hydrologic AEP"):
        load_aep_result(db, request, aoi_geometry=_AOI)


def test_duration_exact_cadence_dry_endpoints_and_binary_values():
    start = datetime(2020, 6, 1, tzinfo=timezone.utc)
    stamps = [(start + timedelta(hours=index)).isoformat().replace("+00:00", "Z") for index in range(4)]
    request = _request("flood_duration", stamps[0], stamps[-1], cadence=1)
    sources = {f"slice_{index}": _source("inundation_time_slice", timestamp=stamp,
               values=np.full((2, 2), int(index in (1, 2)))) for index, stamp in enumerate(stamps)}
    arrays, mask, evidence = validate_duration_sources(request, sources, _AOI)
    assert evidence["gap_policy"] == "reject" and evidence["temporal_resolution_hours"] == 1
    assert np.all(compute_duration_hours(arrays, mask, 1) == 2)
    sources["slice_2"].manifest = sources["slice_2"].manifest.model_copy(
        update={"temporal_coverage": sources["slice_3"].manifest.temporal_coverage})
    with pytest.raises(SourceNotReady, match="gaps"):
        validate_duration_sources(request, sources, _AOI)
    with pytest.raises(SourceNotReady, match="censored"):
        compute_duration_hours([np.ones((2, 2)), np.ones((2, 2)), np.zeros((2, 2))], mask, 1)


def test_annual_manifest_requires_exact_utc_year_and_event_definition():
    data = _data(np.ones((2, 2)))
    good = manifest("annual_inundation_observation", data)
    with pytest.raises(ValidationError, match="event definition"):
        SourceDatasetManifest.model_validate({**good.model_dump(), "event_definition": None})
    with pytest.raises(ValidationError, match="complete January"):
        SourceDatasetManifest.model_validate({**good.model_dump(), "temporal_coverage": {
            "start": "2020-02-01T00:00:00Z", "end": "2020-12-31T23:59:59Z"}})


def test_temporal_products_write_real_cogs_metadata_and_provenance(tmp_path):
    aep_request = _request("flood_aep", "2010-01-01T00:00:00Z", "2019-12-31T23:59:59Z")
    annual = {f"year_{year}": _source("annual_inundation_observation", year=year,
              values=np.full((2, 2), int(year < 2013))) for year in range(2010, 2020)}
    for year, source in zip(range(2010, 2020), annual.values()):
        source.lineage = lambda year=year: {"dataset_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(year))),
                                             "checksum_sha256": str(year)}
    aep = execute_temporal_product(SimpleNamespace(request=aep_request, sources=annual, upstream={},
        lineage=lambda: {role: source.lineage() for role, source in annual.items()}),
        _AOI, tmp_path / "aep", 1, task_id=str(uuid.uuid4()))
    with rasterio.open(tmp_path / "aep" / "flood_aep.cog.tif") as raster:
        assert raster.is_tiled and raster.crs.to_string() == "EPSG:3857"
        np.testing.assert_allclose(raster.read(1, masked=True).compressed(), 0.3, atol=1e-6)
    assert aep.output_files["flood_aep"]["gis_metadata"]["units"] == "annual_probability_0_1"
    assert aep.provenance["record_length_years"] == 10
    assert set(aep.provenance["source_bindings"]) == set(annual)
    assert all(key in aep.output_files for key in ("flood_aep_preview", "flood_aep_csv",
                                                   "flood_aep_excel", "flood_aep_pdf", "report_package"))

    return_request = _request("flood_return_period", "2010-01-01T00:00:00Z", "2019-12-31T23:59:59Z")
    upstream = SimpleNamespace(
        raster_bytes=(tmp_path / "aep" / "flood_aep.cog.tif").read_bytes(),
        result=SimpleNamespace(provenance={"record_length_years": 10,
                                           "event_definition": "fixed annual exceedance threshold",
                                           "derived_uncertainty": {"binomial_standard_error_max": 0.15}}),
        lineage=lambda: {"result_id": str(uuid.uuid4()), "version": 1},
        source_checksums={role: str(year) for year, role in enumerate(annual, 2010)})
    returned = execute_temporal_product(
        SimpleNamespace(request=return_request, sources={}, upstream={"aep": upstream}, lineage=lambda: {}),
        _AOI, tmp_path / "return", 1, task_id=str(uuid.uuid4()))
    with rasterio.open(tmp_path / "return" / "flood_return_period.cog.tif") as raster:
        assert raster.is_tiled
        np.testing.assert_allclose(raster.read(1, masked=True).compressed(), 10 / 3, atol=1e-5)
    assert returned.output_files["flood_return_period"]["gis_metadata"]["units"] == "years"
    assert returned.provenance["upstream_source_checksums"] == upstream.source_checksums

    duration_request = _request("flood_duration", "2020-06-01T00:00:00Z",
                                "2020-06-01T03:00:00Z", cadence=1)
    slices = {f"slice_{index}": _source("inundation_time_slice",
              timestamp=f"2020-06-01T0{index}:00:00Z",
              values=np.full((2, 2), int(index in (1, 2)))) for index in range(4)}
    for index, source in enumerate(slices.values()):
        source.lineage = lambda index=index: {"dataset_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, str(index)))}
    duration = execute_temporal_product(SimpleNamespace(request=duration_request, sources=slices, upstream={},
        lineage=lambda: {role: source.lineage() for role, source in slices.items()}),
        _AOI, tmp_path / "duration", 1, task_id=str(uuid.uuid4()))
    with rasterio.open(tmp_path / "duration" / "flood_duration.cog.tif") as raster:
        assert raster.is_tiled and raster.nodata == -9999
        np.testing.assert_allclose(raster.read(1, masked=True).compressed(), 2)
    assert duration.output_files["flood_duration"]["gis_metadata"]["units"] == "hours"
    assert duration.provenance["processing"]["gap_policy"] == "reject"
