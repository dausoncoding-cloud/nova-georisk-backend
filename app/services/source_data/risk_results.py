"""Fail-closed protected H/E/FII Result verification for source-bound FIRRIS FRI."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from pyproj import CRS

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely.geometry import mapping, shape
from sqlalchemy.orm import Session

from app.core.artifact_storage import artifact_root
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.schemas.source_data import TemporalCoverage
from app.services.source_data.readiness import ReadySource, SourceNotReady, load_registered_source
from app.services.source_data.results import load_hazard_result, load_vulnerability_result


_HAZARD_SOURCES = {"rainfall": "rainfall_stations", "terrain": "terrain_dem",
                   "river_network": "river_drainage_network", "land_cover": "land_cover",
                   "soil": "soil_permeability"}
_EXPOSURE_SOURCES = {"population": "population_density", "buildings": "buildings",
                     "roads": "roads", "critical_infrastructure": "critical_infrastructure",
                     "cropland": "cropland_fraction", "livestock": "livestock_density"}
_INSECURITY_SOURCES = {"capacity": "community_capacity_indicators",
                       "boundaries": "administrative_boundaries"}
_ZONE_MIN = {"moderate": 0.4, "high": 0.6, "extreme": 0.8}


@dataclass(frozen=True)
class ReadyRiskResult:
    result: Result
    checksum_sha256: str
    source_checksums: dict[str, str]
    state_sha256: str
    raster_bytes: bytes | None = None
    scores_by_unit: dict[str, float] | None = None
    unit_geometries: dict[str, dict] | None = None

    def lineage(self) -> dict:
        return {"result_id": str(self.result.id), "version": self.result.version,
                "task_id": str(self.result.task_id), "result_type": self.result.result_type,
                "artifact_sha256": self.checksum_sha256,
                "source_checksums": self.source_checksums,
                "result_state_sha256": self.state_sha256}


def _state_sha(result: Result) -> str:
    encoded = json.dumps({"summary": result.summary, "provenance": result.provenance,
                          "output_files": result.output_files}, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _result(db: Session, result_id: uuid.UUID, request: SourceBoundAnalysisRequest,
            result_type: str) -> Result:
    result = db.get(Result, result_id)
    if (result is None or result.project_id != request.project_id or result.aoi_id != request.aoi_id
            or result.engine_key != "firris" or result.result_type != result_type):
        raise SourceNotReady("Required FIRRIS Result is unavailable in this project and AOI")
    task = db.get(Task, result.task_id)
    if (task is None or task.status != TaskStatus.COMPLETED or task.project_id != request.project_id
            or task.aoi_id != request.aoi_id or task.engine_key != "firris"):
        raise SourceNotReady("Upstream FIRRIS task is not completed")
    return result


def _sources(db: Session, result: Result, request: SourceBoundAnalysisRequest,
             required: dict[str, str], *, optional: dict[str, str] | None = None,
             root: Path | None = None) -> dict[str, ReadySource]:
    provenance = result.provenance
    if not isinstance(provenance, dict):
        raise SourceNotReady("Upstream FIRRIS provenance is invalid")
    pinned = provenance.get("source_bindings")
    optional = optional or {}
    if (not isinstance(pinned, dict) or not set(required).issubset(pinned)
            or not set(pinned).issubset(set(required) | set(optional))):
        raise SourceNotReady("Upstream FIRRIS source lineage is incomplete")
    sources = {}
    for role, lineage in pinned.items():
        if not isinstance(lineage, dict):
            raise SourceNotReady("Upstream FIRRIS source lineage is malformed")
        try:
            source = load_registered_source(db, uuid.UUID(lineage["dataset_id"]), request.project_id, root=root)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceNotReady("Upstream FIRRIS source is unavailable or unapproved") from exc
        if source.manifest.category != {**required, **optional}[role] or source.lineage() != lineage:
            raise SourceNotReady("Upstream FIRRIS source approval, metadata or checksum changed")
        sources[role] = source
    return sources


def _artifact(result: Result, key: str, product_key: str, format_name: str,
              *, root: Path | None = None) -> tuple[dict, bytes, str]:
    if not isinstance(result.output_files, dict):
        raise SourceNotReady("Upstream FIRRIS artifact manifest is invalid")
    entry = result.output_files.get(key)
    if (not isinstance(entry, dict) or entry.get("role") != "product"
            or entry.get("product_key") != product_key or entry.get("format") != format_name
            or entry.get("result_version") != result.version):
        raise SourceNotReady("Upstream protected FIRRIS product is unavailable")
    storage_root = (root or artifact_root()).resolve()
    try:
        path = (storage_root / entry["path"]).resolve(strict=True)
        path.relative_to(storage_root)
    except (KeyError, TypeError, OSError, ValueError) as exc:
        raise SourceNotReady("Upstream FIRRIS artifact is unavailable in protected storage") from exc
    if not path.is_file() or path.stat().st_size > 250 * 1024 * 1024:
        raise SourceNotReady("Upstream FIRRIS artifact is missing or exceeds the size limit")
    data = path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != entry.get("checksum_sha256") or len(data) != entry.get("file_size_bytes"):
        raise SourceNotReady("Upstream FIRRIS artifact checksum or size changed")
    return entry, data, checksum


def _same_period(metadata: dict, request: SourceBoundAnalysisRequest) -> None:
    try:
        period = TemporalCoverage.model_validate(metadata["target_period"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceNotReady("Upstream FIRRIS analysis period is invalid") from exc
    if period != request.period:
        raise SourceNotReady("Upstream FIRRIS analysis periods are not identical")


def _raster(data: bytes, grid, *, nodata: float) -> np.ma.MaskedArray:
    expected = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    try:
        with MemoryFile(data) as memory, memory.open() as raster:
            if (raster.driver != "GTiff" or not raster.is_tiled or raster.count != 1
                    or raster.crs is None or raster.crs.to_string() != grid.crs
                    or raster.width != grid.width or raster.height != grid.height
                    or not raster.transform.almost_equals(expected) or raster.nodata != nodata):
                raise SourceNotReady("Upstream FIRRIS raster grid, CRS, resolution or nodata differs")
            values = raster.read(1, masked=True)
            valid = values.compressed()
            if not len(valid) or not np.isfinite(valid).all() or ((valid < 0) | (valid > 1)).any():
                raise SourceNotReady("Upstream FIRRIS index raster contains invalid values")
            return values
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise SourceNotReady("Upstream FIRRIS COG cannot be read") from exc


def load_risk_results(db: Session, request: SourceBoundAnalysisRequest, *, aoi_geometry: dict,
                      root: Path | None = None) -> dict[str, ReadyRiskResult]:
    """Require exact H/E grids and approved piecewise-constant FII unit geometry."""
    grid = request.target_grid
    try:
        hazard = load_hazard_result(db, request.upstream_results["hazard"], request, root=root)
    except SourceNotReady:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise SourceNotReady("Upstream Hazard Result metadata or provenance is invalid") from exc
    hazard_sources = _sources(db, hazard.result, request, _HAZARD_SOURCES, root=root)
    h_entry = hazard.result.output_files["flood_hazard"]
    h_meta = h_entry["gis_metadata"]
    if not isinstance(h_meta, dict) or h_meta.get("nodata") != -9999.0:
        raise SourceNotReady("Hazard nodata or metadata contract is incompatible with Risk")
    _same_period(h_meta, request)
    h_values = _raster(hazard.raster_bytes, grid, nodata=h_meta["nodata"])
    # The AOI is transformed to the raster CRS before any coverage test.
    from pyproj import Transformer
    from shapely.ops import transform as transform_shape
    aoi_projected = transform_shape(Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform,
                                    shape(aoi_geometry))
    aoi_mask = geometry_mask([mapping(aoi_projected)], out_shape=(grid.height, grid.width),
                             transform=from_bounds(grid.west, grid.south, grid.east, grid.north,
                                                   grid.width, grid.height), invert=True)
    h_valid = ~np.ma.getmaskarray(h_values)
    if not h_valid[aoi_mask].all():
        raise SourceNotReady("Hazard Result does not cover the full AOI grid")

    exposure = _result(db, request.upstream_results["exposure"], request, "source_bound_exposure")
    e_prov = exposure.provenance
    if not isinstance(e_prov, dict) or not isinstance(e_prov.get("upstream_results"), dict):
        raise SourceNotReady("Exposure Result provenance is invalid")
    if (e_prov.get("module") != "exposure"
            or e_prov.get("formula_implementation") != "app.services.firas.exposure.compute_exposure_index"
            or e_prov.get("analysis_readiness_rechecked_at_execution") is not True
            or e_prov["upstream_results"].get("hazard") != hazard.lineage()):
        raise SourceNotReady("Exposure Result does not retain verified Hazard lineage")
    exposure_sources = _sources(db, exposure, request, _EXPOSURE_SOURCES,
                                optional={"economic_assets": "economic_assets"}, root=root)
    e_entry, e_data, e_checksum = _artifact(exposure, "flood_exposure", "flood_exposure", "cog", root=root)
    e_meta = e_entry.get("gis_metadata")
    if not isinstance(e_meta, dict):
        raise SourceNotReady("Exposure GIS metadata is invalid")
    _same_period(e_meta, request)
    expected_bounds = [grid.west, grid.south, grid.east, grid.north]
    if (e_meta.get("crs") != grid.crs or e_meta.get("bounds") != expected_bounds
            or e_meta.get("units") != "index_0_1" or e_meta.get("hazard_result_id") != str(hazard.result.id)
            or e_meta.get("datum") != CRS.from_user_input(grid.crs).datum.name
            or e_meta.get("vertical_datum") != h_meta.get("datum")):
        raise SourceNotReady("Hazard and Exposure CRS, datum, grid or provenance differ")
    threshold = _ZONE_MIN.get(e_meta.get("hazard_min_level"))
    if threshold is None:
        raise SourceNotReady("Exposure Hazard index class is invalid")
    if e_meta.get("nodata") != -9999.0:
        raise SourceNotReady("Exposure nodata contract is incompatible with Risk")
    e_values = _raster(e_data, grid, nodata=e_meta["nodata"])
    zone = aoi_mask & h_valid & (np.asarray(h_values.data, dtype=float) > threshold)
    if not np.array_equal(~np.ma.getmaskarray(e_values), zone):
        raise SourceNotReady("Exposure Result does not cover the exact selected Hazard-index zone")

    insecurity = _result(db, request.upstream_results["insecurity"], request, "source_bound_insecurity")
    i_prov = insecurity.provenance
    if not isinstance(i_prov, dict) or not isinstance(i_prov.get("upstream_results"), dict):
        raise SourceNotReady("FII Result provenance is invalid")
    if (i_prov.get("module") != "insecurity"
            or i_prov.get("formula_implementation") != "app.services.firas.insecurity.compute_fii"
            or i_prov.get("analysis_readiness_rechecked_at_execution") is not True
            or i_prov.get("missing_value_policy") != "reject"):
        raise SourceNotReady("FII Result lacks verified formula and readiness provenance")
    insecurity_sources = _sources(db, insecurity, request, _INSECURITY_SOURCES, root=root)
    fvi_ref = i_prov["upstream_results"].get("vulnerability")
    if not isinstance(fvi_ref, dict):
        raise SourceNotReady("FII lacks upstream FVI Result lineage")
    try:
        fvi_id = uuid.UUID(fvi_ref["result_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceNotReady("FII upstream FVI Result reference is invalid") from exc
    fvi = load_vulnerability_result(db, fvi_id, request,
                                    boundary=insecurity_sources["boundaries"],
                                    aoi_geometry=aoi_geometry, root=root)
    if fvi_ref != fvi.lineage():
        raise SourceNotReady("FII upstream FVI Result version or checksum changed")
    i_entry, i_data, i_checksum = _artifact(insecurity, "insecurity_vector", "flood_insecurity", "geojson", root=root)
    i_meta = i_entry.get("gis_metadata")
    if not isinstance(i_meta, dict):
        raise SourceNotReady("FII GIS metadata is invalid")
    _same_period(i_meta, request)
    if (i_meta.get("crs") != "EPSG:4326" or i_meta.get("datum") != "WGS84"
            or i_meta.get("units") != "index_0_1"
            or i_meta.get("spatial_support") != "reviewed administrative unit polygon"):
        raise SourceNotReady("FII spatial-unit CRS, datum or units are incompatible")
    try:
        bounds = i_meta["bounding_box"]
        if any(not math.isclose(float(bounds[key]), value, abs_tol=1e-9)
               for key, value in zip(("west", "south", "east", "north"), shape(aoi_geometry).bounds)):
            raise ValueError("FII bounds differ from AOI")
        document = json.loads(i_data)
        if document["type"] != "FeatureCollection" or not isinstance(document["features"], list):
            raise ValueError("FII is not a FeatureCollection")
        geometries = {}
        scores = {}
        for feature in document["features"]:
            unit = feature["properties"]["spatial_unit_id"]
            value = float(feature["properties"]["fii_index"])
            if (unit in scores or unit not in fvi.scores_by_unit or not math.isfinite(value)
                    or not 0 <= value <= 1):
                raise ValueError("FII score or spatial-unit ID is invalid")
            geom = shape(feature["geometry"])
            if geom.is_empty or not geom.is_valid:
                raise ValueError("FII geometry is invalid")
            geometries[unit], scores[unit] = feature["geometry"], value
        if set(scores) != set(fvi.scores_by_unit) or len(scores) < 2:
            raise ValueError("FII unit coverage differs from FVI")
        source_features = json.loads(insecurity_sources["boundaries"].data)["features"]
        expected = {}
        for feature in source_features:
            clipped = shape(feature["geometry"]).intersection(shape(aoi_geometry))
            if not clipped.is_empty and clipped.area > 0:
                unit = feature["properties"]["spatial_unit_id"]
                if unit in expected:
                    raise ValueError("duplicate approved boundary unit")
                expected[unit] = clipped
        if set(expected) != set(scores) or any(not shape(geometries[unit]).equals(expected[unit]) for unit in expected):
            raise ValueError("FII polygons differ from approved boundary clipping")
        summary = (insecurity.summary or {})["scores_by_spatial_unit"]
        if set(summary) != set(scores) or any(not math.isclose(float(summary[unit]), value, abs_tol=1e-9)
                                              for unit, value in scores.items()):
            raise ValueError("FII vector and Result summary disagree")
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceNotReady("FII spatial-unit layer is incomplete or invalid") from exc
    return {
        "hazard": ReadyRiskResult(hazard.result, hazard.checksum_sha256,
            {role: source.manifest.sha256.lower() for role, source in hazard_sources.items()},
            _state_sha(hazard.result), raster_bytes=hazard.raster_bytes),
        "exposure": ReadyRiskResult(exposure, e_checksum,
            {role: source.manifest.sha256.lower() for role, source in exposure_sources.items()},
            _state_sha(exposure), raster_bytes=e_data),
        "insecurity": ReadyRiskResult(insecurity, i_checksum,
            {role: source.manifest.sha256.lower() for role, source in insecurity_sources.items()},
            _state_sha(insecurity), scores_by_unit=scores, unit_geometries=geometries),
    }
