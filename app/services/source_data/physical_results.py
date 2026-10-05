"""Verify protected source-bound depth/velocity Results before product Hazard."""
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


_ROLES = {
    "depth": {"water_surface": "water_surface_elevation", "terrain": "terrain_dem"},
    "velocity": {"model_velocity": "hydraulic_model_velocity"},
}


@dataclass(frozen=True)
class ReadyPhysicalResult:
    result: Result
    raster_bytes: bytes
    checksum_sha256: str
    source_checksums: dict[str, str]
    state_sha256: str

    def lineage(self) -> dict:
        return {"result_id": str(self.result.id), "version": self.result.version,
                "task_id": str(self.result.task_id), "result_type": self.result.result_type,
                "artifact_sha256": self.checksum_sha256,
                "source_checksums": self.source_checksums,
                "result_state_sha256": self.state_sha256}


def load_physical_results(db: Session, request: SourceBoundAnalysisRequest, *,
                          aoi_geometry: dict, root: Path | None = None) -> dict[str, ReadyPhysicalResult]:
    grid = request.target_grid
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    aoi = transform_geom("EPSG:4326", grid.crs, aoi_geometry)
    aoi_mask = geometry_mask([aoi], out_shape=(grid.height, grid.width), transform=transform, invert=True)
    if not aoi_mask.any():
        raise SourceNotReady("Physical product grid has no AOI cells")
    ready = {}
    for role, required in _ROLES.items():
        result = db.get(Result, request.upstream_results[role])
        if (result is None or result.project_id != request.project_id or result.aoi_id != request.aoi_id
                or result.engine_key != "firris" or result.result_type != f"source_bound_flood_{role}"):
            raise SourceNotReady("Required protected physical FIRRIS Result is unavailable in this project and AOI")
        task = db.get(Task, result.task_id)
        if (task is None or task.status != TaskStatus.COMPLETED or task.project_id != request.project_id
                or task.aoi_id != request.aoi_id or task.engine_key != "firris"):
            raise SourceNotReady("Upstream physical FIRRIS task is not completed")
        provenance = result.provenance
        if (not isinstance(provenance, dict) or provenance.get("module") != f"flood_{role}"
                or provenance.get("analysis_readiness_rechecked_at_execution") is not True
                or provenance.get("formula_implementation") != (
                    "app.services.maps.flood_products.compute_flood_depth" if role == "depth"
                    else "approved hydraulic-model velocity raster; no inferred velocity")
                or not isinstance(provenance.get("source_bindings"), dict)
                or set(provenance["source_bindings"]) != set(required)):
            raise SourceNotReady("Upstream physical Result lacks verified source and formula provenance")
        source_checksums = {}
        for source_role, category in required.items():
            pinned = provenance["source_bindings"][source_role]
            if not isinstance(pinned, dict):
                raise SourceNotReady("Upstream source lineage is malformed")
            try:
                source = load_registered_source(db, uuid.UUID(pinned["dataset_id"]), request.project_id, root=root)
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceNotReady("Upstream physical source is no longer approved") from exc
            if source.manifest.category != category or source.lineage() != pinned:
                raise SourceNotReady("Upstream physical source version, checksum or approval changed")
            source_checksums[source_role] = source.manifest.sha256.lower()
        key = f"flood_{role}"
        entry, data, checksum = _artifact(result, key, key, "cog", root=root)
        meta = entry.get("gis_metadata")
        if not isinstance(meta, dict):
            raise SourceNotReady("Upstream physical GIS metadata is invalid")
        _same_period(meta, request)
        if (meta.get("crs") != grid.crs or meta.get("bounds") != [grid.west, grid.south, grid.east, grid.north]
                or meta.get("units") != ("m" if role == "depth" else "m/s")
                or meta.get("nodata") != -9999.0 or meta.get("result_version") != result.version):
            raise SourceNotReady("Upstream physical grid, units, nodata or version is incompatible")
        if role == "depth" and (not meta.get("vertical_datum")
                                 or meta["vertical_datum"] != provenance["source_bindings"]["terrain"]["vertical_datum"]
                                 or meta["vertical_datum"] != provenance["source_bindings"]["water_surface"]["vertical_datum"]):
            raise SourceNotReady("Depth Result vertical datum is missing or changed")
        try:
            with MemoryFile(data) as memory, memory.open() as raster:
                if (raster.driver != "GTiff" or not raster.is_tiled or raster.count != 1
                        or raster.crs is None or raster.crs.to_string() != grid.crs
                        or raster.width != grid.width or raster.height != grid.height
                        or not raster.transform.almost_equals(transform) or raster.nodata != -9999.0):
                    raise SourceNotReady("Upstream physical raster grid or CRS differs")
                values = raster.read(1, masked=True)
                valid = ~np.ma.getmaskarray(values)
                if (not valid[aoi_mask].all() or not np.isfinite(values.compressed()).all()
                        or (values.compressed() < 0).any()):
                    raise SourceNotReady("Upstream physical raster has uncovered or invalid AOI cells")
        except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
            raise SourceNotReady("Upstream physical raster cannot be read") from exc
        ready[role] = ReadyPhysicalResult(result, data, checksum, source_checksums, _state_sha(result))
    return ready
