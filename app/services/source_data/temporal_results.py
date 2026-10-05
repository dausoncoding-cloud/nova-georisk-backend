"""Fail-closed protected empirical AEP Result verification for return period."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform_geom
from sqlalchemy.orm import Session

from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.services.source_data.readiness import SourceNotReady, load_registered_source
from app.services.source_data.risk_results import _artifact, _same_period, _state_sha


_AEP_METHOD = "empirical annual event exceedance count / complete observation years"


@dataclass(frozen=True)
class ReadyAEPResult:
    result: Result
    raster_bytes: bytes
    checksum_sha256: str
    source_checksums: dict[str, str]
    state_sha256: str

    def lineage(self) -> dict:
        return {"result_id": str(self.result.id), "version": self.result.version,
                "task_id": str(self.result.task_id), "result_type": self.result.result_type,
                "artifact_sha256": self.checksum_sha256, "source_checksums": self.source_checksums,
                "result_state_sha256": self.state_sha256}


def load_aep_result(db: Session, request: SourceBoundAnalysisRequest, *, aoi_geometry: dict,
                    root: Path | None = None) -> ReadyAEPResult:
    result = db.get(Result, request.upstream_results["aep"])
    if (result is None or result.project_id != request.project_id or result.aoi_id != request.aoi_id
            or result.engine_key != "firris" or result.result_type != "source_bound_flood_aep"):
        raise SourceNotReady("Protected hydrologic AEP Result is unavailable in this project and AOI")
    task = db.get(Task, result.task_id)
    if (task is None or task.status != TaskStatus.COMPLETED or task.project_id != request.project_id
            or task.aoi_id != request.aoi_id or task.engine_key != "firris"):
        raise SourceNotReady("Upstream AEP task is not completed")
    provenance = result.provenance
    if (not isinstance(provenance, dict) or provenance.get("module") != "flood_aep"
            or provenance.get("formula_implementation") != _AEP_METHOD
            or provenance.get("analysis_readiness_rechecked_at_execution") is not True
            or not provenance.get("event_definition")
            or not isinstance(provenance.get("source_bindings"), dict)):
        raise SourceNotReady("Upstream Result is not a verified hydrologic AEP product")
    grid = request.target_grid
    years = list(range(request.period.start.year, request.period.end.year + 1))
    if (len(years) < 10 or len(years) != provenance.get("record_length_years")
            or set(provenance["source_bindings"]) != {f"year_{year}" for year in years}):
        raise SourceNotReady("AEP Result does not retain a sufficient complete annual record")
    source_checksums = {}
    for year in years:
        role = f"year_{year}"
        pinned = provenance["source_bindings"][role]
        if not isinstance(pinned, dict):
            raise SourceNotReady("AEP source lineage is malformed")
        try:
            source = load_registered_source(db, uuid.UUID(pinned["dataset_id"]), request.project_id, root=root)
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceNotReady("Annual source is no longer approved") from exc
        if (source.manifest.category != "annual_inundation_observation"
                or source.manifest.observation_year != year
                or source.manifest.event_definition != provenance["event_definition"]
                or not source.evidence.get("checks", {}).get("annual_record_complete_verified")
                or source.lineage() != pinned):
            raise SourceNotReady("AEP source approval, year, definition or checksum changed")
        source_checksums[role] = source.manifest.sha256.lower()
    entry, data, checksum = _artifact(result, "flood_aep", "flood_aep", "cog", root=root)
    meta = entry.get("gis_metadata")
    if not isinstance(meta, dict):
        raise SourceNotReady("AEP GIS metadata is invalid")
    _same_period(meta, request)
    if (meta.get("crs") != grid.crs or meta.get("bounds") != [grid.west, grid.south, grid.east, grid.north]
            or meta.get("units") != "annual_probability_0_1" or meta.get("nodata") != -9999.0
            or meta.get("result_version") != result.version or meta.get("frequency_method") != _AEP_METHOD
            or meta.get("record_length_years") != len(years)):
        raise SourceNotReady("AEP grid, units, period, method or version is incompatible")
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    aoi_mask = geometry_mask([transform_geom("EPSG:4326", grid.crs, aoi_geometry)],
                             out_shape=(grid.height, grid.width), transform=transform, invert=True)
    try:
        with MemoryFile(data) as memory, memory.open() as raster:
            if (raster.driver != "GTiff" or not raster.is_tiled or raster.count != 1 or raster.crs is None
                    or raster.crs.to_string() != grid.crs or raster.width != grid.width
                    or raster.height != grid.height or not raster.transform.almost_equals(transform)
                    or raster.nodata != -9999.0):
                raise SourceNotReady("AEP raster grid or CRS differs")
            values = raster.read(1, masked=True)
            valid = ~np.ma.getmaskarray(values)
            observed = values.compressed()
            if (not aoi_mask.any() or not np.array_equal(valid, aoi_mask) or not np.isfinite(observed).all()
                    or ((observed < 0) | (observed > 1)).any()
                    or (np.asarray(values.data)[aoi_mask] <= 0).any()):
                raise SourceNotReady("AEP has uncovered, zero or invalid cells; full-AOI return period is undefined")
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise SourceNotReady("AEP COG cannot be read") from exc
    return ReadyAEPResult(result, data, checksum, source_checksums, _state_sha(result))
