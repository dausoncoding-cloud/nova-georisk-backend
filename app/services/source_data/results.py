"""Revalidate a protected, source-bound Hazard Result before downstream science."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from sqlalchemy.orm import Session
from shapely.geometry import shape

from app.core.artifact_storage import artifact_root
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.schemas.source_data import TemporalCoverage
from app.services.source_data.readiness import ReadySource, SourceNotReady, load_registered_source


@dataclass(frozen=True)
class ReadyHazardResult:
    result: Result
    raster_bytes: bytes
    checksum_sha256: str
    source_checksums: dict[str, str]

    def lineage(self) -> dict:
        return {
            "result_id": str(self.result.id), "version": self.result.version,
            "task_id": str(self.result.task_id), "result_type": self.result.result_type,
            "artifact_sha256": self.checksum_sha256,
            "source_checksums": self.source_checksums,
        }


def load_hazard_result(db: Session, result_id: uuid.UUID, request: SourceBoundAnalysisRequest,
                       *, root: Path | None = None) -> ReadyHazardResult:
    result = db.get(Result, result_id)
    if (result is None or result.project_id != request.project_id or result.aoi_id != request.aoi_id
            or result.engine_key != "firris" or result.result_type != "source_bound_hazard"):
        raise SourceNotReady("Hazard Result is unavailable in this project and AOI")
    task = db.get(Task, result.task_id)
    if task is None or task.status != TaskStatus.COMPLETED or task.project_id != request.project_id:
        raise SourceNotReady("Upstream Hazard task is not completed")
    provenance = result.provenance or {}
    if (provenance.get("module") != "hazard" or
            provenance.get("formula_implementation") != "app.services.firas.hazard.compute_hazard_index" or
            provenance.get("analysis_readiness_rechecked_at_execution") is not True):
        raise SourceNotReady("Upstream Hazard Result lacks verified formula provenance")
    source_lineage = provenance.get("source_bindings")
    if not isinstance(source_lineage, dict) or set(source_lineage) != {"rainfall", "terrain", "river_network", "land_cover", "soil"}:
        raise SourceNotReady("Upstream Hazard source lineage is incomplete")
    source_checksums = {}
    for role, pinned in source_lineage.items():
        if not isinstance(pinned, dict):
            raise SourceNotReady("Upstream Hazard source lineage is malformed")
        try:
            source = load_registered_source(db, uuid.UUID(pinned["dataset_id"]), request.project_id, root=root)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceNotReady("Upstream Hazard source is unavailable or unapproved") from exc
        if (source.manifest.sha256.lower() != pinned.get("sha256") or
                source.evidence.get("reviewed_at") != pinned.get("readiness_evidence", {}).get("reviewed_at")):
            raise SourceNotReady("Upstream Hazard source approval or checksum changed")
        source_checksums[role] = source.manifest.sha256.lower()
    entry = (result.output_files or {}).get("flood_hazard")
    if not isinstance(entry, dict) or entry.get("format") != "cog" or entry.get("role") != "product":
        raise SourceNotReady("Upstream Hazard COG is unavailable")
    metadata = entry.get("gis_metadata") or {}
    grid = request.target_grid
    expected_bounds = [grid.west, grid.south, grid.east, grid.north]
    if (entry.get("product_key") != "flood_hazard" or metadata.get("units") != "index_0_1"
            or metadata.get("crs") != grid.crs or metadata.get("bounds") != expected_bounds
            or entry.get("result_version") != result.version):
        raise SourceNotReady("Upstream Hazard grid or units do not match Exposure")
    try:
        period = TemporalCoverage.model_validate(metadata["target_period"])
    except (KeyError, ValueError) as exc:
        raise SourceNotReady("Upstream Hazard period metadata is invalid") from exc
    if period.start > request.period.start or period.end < request.period.end:
        raise SourceNotReady("Upstream Hazard period does not cover Exposure")
    storage_root = (root or artifact_root()).resolve()
    try:
        path = (storage_root / entry["path"]).resolve(strict=True)
        path.relative_to(storage_root)
    except (KeyError, OSError, ValueError) as exc:
        raise SourceNotReady("Upstream Hazard artifact is unavailable in protected storage") from exc
    if not path.is_file() or path.stat().st_size > 250 * 1024 * 1024:
        raise SourceNotReady("Upstream Hazard artifact is missing or exceeds the size limit")
    data = path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != entry.get("checksum_sha256"):
        raise SourceNotReady("Upstream Hazard artifact checksum changed")
    try:
        with MemoryFile(data) as memory, memory.open() as raster:
            expected_transform = from_bounds(*expected_bounds, grid.width, grid.height)
            if (raster.driver != "GTiff" or not raster.is_tiled or raster.count != 1
                    or raster.crs is None or raster.crs.to_string() != grid.crs
                    or raster.width != grid.width or raster.height != grid.height
                    or not raster.transform.almost_equals(expected_transform)
                    or raster.nodata != metadata.get("nodata")):
                raise SourceNotReady("Upstream Hazard COG georeferencing is incompatible")
            values = raster.read(1, masked=True).compressed()
            if not len(values) or not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
                raise SourceNotReady("Upstream Hazard index contains invalid values")
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise SourceNotReady("Upstream Hazard COG cannot be read") from exc
    return ReadyHazardResult(result, data, checksum, source_checksums)


@dataclass(frozen=True)
class ReadyVulnerabilityResult:
    result: Result
    scores_by_unit: dict[str, float]
    checksum_sha256: str
    source_checksums: dict[str, str]
    state_sha256: str

    def lineage(self) -> dict:
        return {
            "result_id": str(self.result.id), "version": self.result.version,
            "task_id": str(self.result.task_id), "result_type": self.result.result_type,
            "artifact_sha256": self.checksum_sha256, "source_checksums": self.source_checksums,
            "result_state_sha256": self.state_sha256,
        }


def load_vulnerability_result(db: Session, result_id: uuid.UUID, request: SourceBoundAnalysisRequest,
                              *, boundary: ReadySource, aoi_geometry: dict,
                              root: Path | None = None) -> ReadyVulnerabilityResult:
    """Bind a completed FVI, rechecking immutable bytes, approval and unit geometry."""
    result = db.get(Result, result_id)
    if (result is None or result.project_id != request.project_id or result.aoi_id != request.aoi_id
            or result.engine_key != "firris" or result.result_type != "source_bound_vulnerability"):
        raise SourceNotReady("Vulnerability Result is unavailable in this project and AOI")
    task = db.get(Task, result.task_id)
    if (task is None or task.status != TaskStatus.COMPLETED or task.project_id != request.project_id
            or task.aoi_id != request.aoi_id or task.engine_key != "firris"):
        raise SourceNotReady("Upstream Vulnerability task is not completed")
    provenance = result.provenance or {}
    if (provenance.get("module") != "vulnerability"
            or provenance.get("formula_implementation") != "app.services.firas.vulnerability.compute_fvi"
            or provenance.get("missing_value_policy") != "reject"
            or provenance.get("analysis_readiness_rechecked_at_execution") is not True):
        raise SourceNotReady("Upstream FVI lacks verified formula and readiness provenance")
    lineage = provenance.get("source_bindings")
    if not isinstance(lineage, dict) or set(lineage) != {"indicators", "boundaries"}:
        raise SourceNotReady("Upstream FVI source lineage is incomplete")
    source_checksums = {}
    for role, pinned in lineage.items():
        if not isinstance(pinned, dict):
            raise SourceNotReady("Upstream FVI source lineage is malformed")
        try:
            source = load_registered_source(db, uuid.UUID(pinned["dataset_id"]), request.project_id, root=root)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceNotReady("Upstream FVI source is unavailable or unapproved") from exc
        if source.lineage() != pinned:
            raise SourceNotReady("Upstream FVI source approval, metadata or checksum changed")
        source_checksums[role] = source.manifest.sha256.lower()
    if (lineage["boundaries"].get("dataset_id") != str(boundary.dataset.id)
            or source_checksums["boundaries"] != boundary.manifest.sha256.lower()):
        raise SourceNotReady("FVI and FII must use the same approved spatial-unit boundary version")
    entry = (result.output_files or {}).get("vulnerability_vector")
    if (not isinstance(entry, dict) or entry.get("role") != "product"
            or entry.get("format") != "geojson" or entry.get("product_key") != "flood_vulnerability"
            or entry.get("result_version") != result.version):
        raise SourceNotReady("Upstream protected FVI spatial layer is unavailable")
    metadata = entry.get("gis_metadata") or {}
    if (metadata.get("crs") != "EPSG:4326" or metadata.get("datum") != "WGS84"
            or metadata.get("units") != "index_0_1"
            or metadata.get("spatial_support") != "reviewed administrative unit polygon"):
        raise SourceNotReady("Upstream FVI spatial metadata is incompatible")
    try:
        period = TemporalCoverage.model_validate(metadata["target_period"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceNotReady("Upstream FVI period metadata is invalid") from exc
    if period.start > request.period.start or period.end < request.period.end:
        raise SourceNotReady("Upstream FVI period does not cover Flood Insecurity")
    storage_root = (root or artifact_root()).resolve()
    try:
        path = (storage_root / entry["path"]).resolve(strict=True)
        path.relative_to(storage_root)
    except (KeyError, OSError, ValueError) as exc:
        raise SourceNotReady("Upstream FVI artifact is unavailable in protected storage") from exc
    if not path.is_file() or path.stat().st_size > 100 * 1024 * 1024:
        raise SourceNotReady("Upstream FVI artifact is missing or exceeds the size limit")
    data = path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != entry.get("checksum_sha256") or len(data) != entry.get("file_size_bytes"):
        raise SourceNotReady("Upstream FVI artifact checksum or size changed")
    try:
        document = json.loads(data)
        features = document["features"]
        if document["type"] != "FeatureCollection" or not isinstance(features, list):
            raise ValueError("not a FeatureCollection")
        aoi = shape(aoi_geometry)
        actual_bounds = metadata.get("bounding_box") or {}
        if any(not math.isclose(float(actual_bounds[key]), value, abs_tol=1e-9)
               for key, value in zip(("west", "south", "east", "north"), aoi.bounds)):
            raise ValueError("FVI bounding box does not match AOI")
        expected = {}
        for feature in json.loads(boundary.data)["features"]:
            clipped = shape(feature["geometry"]).intersection(aoi)
            if not clipped.is_empty and clipped.area > 0:
                unit = feature["properties"]["spatial_unit_id"]
                if unit in expected:
                    raise ValueError("duplicate source spatial unit")
                expected[unit] = clipped
        scores = {}
        for feature in features:
            unit = feature["properties"]["spatial_unit_id"]
            value = float(feature["properties"]["fvi_index"])
            if unit in scores or unit not in expected or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("missing, duplicate or invalid FVI spatial-unit score")
            if not shape(feature["geometry"]).equals(expected[unit]):
                raise ValueError("FVI polygon does not match approved boundary clipping")
            scores[unit] = value
        if set(scores) != set(expected) or len(scores) < 2:
            raise ValueError("FVI spatial-unit inventory is incomplete")
        summary_scores = (result.summary or {})["scores_by_spatial_unit"]
        if set(summary_scores) != set(scores) or any(not math.isclose(float(summary_scores[unit]), value, abs_tol=1e-9)
                                                   for unit, value in scores.items()):
            raise ValueError("FVI vector and Result summary disagree")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceNotReady("Upstream FVI spatial layer or summary is invalid") from exc
    state_bytes = json.dumps({"summary": result.summary, "provenance": result.provenance,
                              "output_files": result.output_files}, sort_keys=True, default=str).encode()
    state_sha256 = hashlib.sha256(state_bytes).hexdigest()
    return ReadyVulnerabilityResult(result, scores, checksum, source_checksums, state_sha256)
