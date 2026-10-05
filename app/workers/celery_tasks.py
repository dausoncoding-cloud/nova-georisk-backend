"""
Celery task shells for long-running GEE/geoprocessing jobs.

Each task follows the same pattern: load the Task row, flip its status
Queued -> Running, do the work via the relevant service, write the
Result row(s), flip status -> Completed/Failed.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.artifact_storage import require_artifact_storage_ready
from app.db.session import SessionLocal
from app.models.result import Result
from app.models.aoi import AOI
from app.services.source_data.boundaries import revalidate_boundary_aoi
from app.models.task import Task, TaskStatus
from app.platform.engines import get_engine_adapter
from app.platform.engines.base import EngineExecutionContext
from app.platform.result_exports import artifact_fingerprint
from sqlalchemy import func
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

logger = logging.getLogger(__name__)


def _mark_running(db, task: Task) -> None:
    if task.status == TaskStatus.CANCELED:
        return
    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now(timezone.utc)
    task.error_summary = None
    db.commit()


def _mark_completed(db, task: Task, result_payload: dict) -> None:
    db.refresh(task)
    if task.status == TaskStatus.CANCELED:
        return
    task.status = TaskStatus.COMPLETED
    task.progress_pct = 100
    task.result_payload = result_payload
    task.completed_at = datetime.now(timezone.utc)
    db.commit()


def _mark_failed(db, task: Task, error: Exception) -> None:
    db.refresh(task)
    if task.status == TaskStatus.CANCELED:
        return
    task.status = TaskStatus.FAILED
    # Raw exceptions remain server-side for diagnosis.  API responses expose
    # only this stable, non-sensitive summary.
    task.error_message = str(error)
    if isinstance(getattr(error, "quality_record", None), dict):
        task.result_payload = {"quality": error.quality_record}
    task.error_summary = "Analysis execution failed. Please retry or contact support with the request ID."
    task.completed_at = datetime.now(timezone.utc)
    db.commit()


@celery_app.task(name="nova.tasks.run_flood_screening_atlas", bind=True)
def run_flood_screening_atlas(self, task_id: str) -> None:
    """
    Generates the flood screening atlas (true colour, NDVI, MNDWI,
    NDBI, SAR change/severity/binary-extent screen, elevation, slope,
    TPI, TWI, distance-to-water, rainfall, land cover, hazard
    index+class) for whichever project/AOI is named in the task's
    input_params — generic, not tied to any specific location.

    Expects task.input_params = {
        "project_id": str, "aoi_id": str, "aoi_geometry": dict (GeoJSON),
        "target_start": "YYYY-MM-DD", "target_end": "YYYY-MM-DD",
        "baseline_start": "YYYY-MM-DD", "baseline_end": "YYYY-MM-DD",
    }
    """
    # Imported here, not at module level, so importing this module (e.g. for
    # the API layer's TaskType wiring) never requires the `ee` package to be
    # installed/importable unless a GEE task actually runs.
    from app.services.gee.atlas_orchestrator import generate_flood_screening_atlas

    db = SessionLocal()
    task = None
    result = None
    try:
        task = db.get(Task, uuid.UUID(task_id))
        if task is None:
            return
        _mark_running(db, task)

        params = task.input_params or {}
        required = ["project_id", "aoi_id", "aoi_geometry", "target_start", "target_end", "baseline_start", "baseline_end"]
        missing = [k for k in required if k not in params]
        if missing:
            raise ValueError(f"Missing required input_params: {missing}")

        def _progress(pct: int) -> None:
            task.progress_pct = pct
            db.commit()

        next_version = (
            db.query(func.max(Result.version))
            .filter(
                Result.project_id == task.project_id,
                Result.aoi_id == task.aoi_id,
                Result.engine_key == task.engine_key,
                Result.result_type == "screening_atlas",
            )
            .scalar()
            or 0
        ) + 1
        result = Result(
            task_id=task.id,
            engine_key=task.engine_key,
            project_id=task.project_id,
            aoi_id=task.aoi_id,
            result_type="screening_atlas",
            version=next_version,
            summary={"status": "running"},
            output_files={},
        )
        db.add(result)
        db.flush()
        output_root = require_artifact_storage_ready()
        manifest = generate_flood_screening_atlas(
            project_id=params["project_id"],
            aoi_id=params["aoi_id"],
            aoi_geometry=params["aoi_geometry"],
            target_start=params["target_start"],
            target_end=params["target_end"],
            baseline_start=params["baseline_start"],
            baseline_end=params["baseline_end"],
            output_root=output_root,
            progress_callback=_progress,
            result_id=str(result.id),
            version=next_version,
        )

        manifest_dict = manifest.to_dict()
        result.summary = manifest_dict
        result.provenance = manifest.provenance
        result.output_files = {}
        relative_directory = Path(str(task.project_id)) / str(task.aoi_id) / str(result.id)
        for product in manifest.products:
            relative_path = relative_directory / product["filename"]
            size, checksum = artifact_fingerprint(output_root / relative_path)
            bounds = product.get("bounds") or []
            bounding_box = None
            if len(bounds) == 4:
                bounding_box = {
                    "west": bounds[0],
                    "south": bounds[1],
                    "east": bounds[2],
                    "north": bounds[3],
                }
            result.output_files[product["key"]] = {
                "path": str(relative_path),
                "download_name": product["filename"],
                "label": product["label"],
                "media_type": "image/png",
                "artifact_type": "preview",
                "role": "product",
                "product_key": product["key"],
                "delivery_type": "preview",
                "format": "png",
                "schema_version": "1.0",
                "result_version": next_version,
                "file_size_bytes": size,
                "checksum_sha256": checksum,
                "gis_metadata": {
                    "crs": product.get("crs"),
                    "bounding_box": bounding_box,
                    "width": product.get("width"),
                    "height": product.get("height"),
                    "units": product.get("units"),
                    "nodata": product.get("nodata"),
                    "legend": product.get("legend"),
                },
                "layer": {
                    "layer_type": "raster",
                    "crs": product.get("crs"),
                    "bounding_box": bounding_box,
                    "spatial_resolution": None,
                    "units": product.get("units"),
                    "nodata": product.get("nodata"),
                    "legend": product.get("legend"),
                    "renderable": True,
                    "rendering_reason": None,
                    "available_delivery_types": ["preview"],
                    "planned_delivery_types": ["geotiff", "cog"],
                },
            }

        _mark_completed(db, task, manifest_dict)
    except Exception as exc:  # noqa: BLE001 - task boundary, must not raise
        logger.exception("FIRRIS atlas task failed task_id=%s", task_id)
        db.rollback()
        if task is None:
            task = db.get(Task, uuid.UUID(task_id))
        if result is not None:
            persisted_result = db.get(Result, result.id)
            if persisted_result is not None:
                persisted_result.summary = {
                    "status": "failed",
                    "message": "Atlas generation failed.",
                }
                db.commit()
        if task:
            _mark_failed(db, task, exc)
    finally:
        db.close()


def execute_engine_task(db, task_id: uuid.UUID) -> None:
    """Execute one persisted engine job; kept session-injectable for integration tests."""
    task = db.get(Task, task_id)
    if task is None or task.status == TaskStatus.CANCELED:
        return
    result = None
    try:
        _mark_running(db, task)
        params = task.input_params or {}
        aoi = db.get(AOI, task.aoi_id)
        if aoi is None:
            raise ValueError("Analysis AOI is unavailable")
        revalidate_boundary_aoi(db, aoi)
        adapter = get_engine_adapter(task.engine_key)
        metadata = dict(params.get("gis_metadata") or {})
        metadata["producer"] = "NOVA GeoRisk"
        metadata["engine_version"] = adapter.version

        next_version = (
            db.query(func.max(Result.version))
            .filter(
                Result.project_id == task.project_id,
                Result.aoi_id == task.aoi_id,
                Result.engine_key == task.engine_key,
                Result.result_type == params.get("operation", "analysis"),
            )
            .scalar()
            or 0
        ) + 1
        result = Result(
            task_id=task.id,
            engine_key=task.engine_key,
            project_id=task.project_id,
            aoi_id=task.aoi_id,
            result_type=params.get("operation", "analysis"),
            version=next_version,
            summary={"status": "running"},
            output_files={},
        )
        db.add(result)
        db.flush()

        relative_directory = Path(str(task.project_id)) / str(task.aoi_id) / str(result.id)
        output_directory = require_artifact_storage_ready() / relative_directory

        def _progress(value: int) -> None:
            db.refresh(task)
            if task.status != TaskStatus.CANCELED:
                task.progress_pct = max(0, min(99, value))
                db.commit()

        if "source_binding" in params and task.engine_key == "firris":
            from app.schemas.source_bindings import SourceBoundAnalysisRequest
            from app.services.source_data.bindings import resolve_bindings
            from app.services.source_data.science import execute_survey_module
            from app.services.source_data.hazard import execute_hazard_module
            from app.services.source_data.exposure import execute_exposure_module
            from app.services.source_data.vulnerability import execute_vulnerability_module
            from app.services.source_data.insecurity import execute_insecurity_module
            from app.services.source_data.risk import execute_risk_module
            from app.services.source_data.resilience import execute_resilience_module
            from app.services.source_data.physical_products import execute_physical_product
            from app.services.source_data.temporal_products import execute_temporal_product
            from app.services.source_data.derived_maps import execute_derived_map
            request = SourceBoundAnalysisRequest.model_validate(params["source_binding"])
            if request.project_id != task.project_id or request.aoi_id != task.aoi_id:
                raise ValueError("Source binding identity does not match the persisted task")
            aoi = db.get(AOI, task.aoi_id)
            if aoi is None:
                raise ValueError("Source-bound AOI is missing")
            resolved = resolve_bindings(db, request, aoi_geometry=mapping(to_shape(aoi.geometry)))
            snapshots = params.get("source_snapshot") or {}
            if set(snapshots) != set(resolved.sources):
                raise ValueError("Source snapshot roles changed after submission")
            for role, source in resolved.sources.items():
                pinned = snapshots[role]
                if (pinned.get("dataset_id") != str(source.dataset.id)
                    or pinned.get("sha256") != source.manifest.sha256.lower()
                    or pinned.get("reviewed_at") != source.evidence.get("reviewed_at")):
                    raise ValueError("Source approval or version changed after submission")
                if request.module == "flood_change":
                    from app.services.source_data.change import comparison_source_fingerprint
                    if pinned.get("comparison_manifest_sha256") != comparison_source_fingerprint(source):
                        raise ValueError("Comparison source metadata changed after submission")
            result_snapshots = params.get("result_snapshot") or {}
            if result_snapshots != {role: upstream.lineage() for role, upstream in resolved.upstream.items()}:
                raise ValueError("Upstream Result approval, version or artifact changed after submission")
            if request.module == "satellite_preprocessing":
                from app.services.source_data.satellite_preprocessing import execute_satellite_preprocessing
                execution = execute_satellite_preprocessing(resolved, mapping(to_shape(aoi.geometry)),
                    output_directory, next_version, task_id=str(task.id))
            elif request.module == "flood_change":
                from app.services.source_data.change import execute_change_product
                execution = execute_change_product(resolved, mapping(to_shape(aoi.geometry)),
                    output_directory, next_version, task_id=str(task.id))
            elif request.module == "hazard":
                execution = execute_hazard_module(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module == "exposure":
                execution = execute_exposure_module(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module == "vulnerability":
                execution = execute_vulnerability_module(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module == "insecurity":
                execution = execute_insecurity_module(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module == "risk":
                execution = execute_risk_module(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module == "resilience":
                execution = execute_resilience_module(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module in {"flood_depth", "flood_velocity", "flood_hazard_product"}:
                execution = execute_physical_product(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module in {"flood_aep", "flood_return_period", "flood_duration"}:
                execution = execute_temporal_product(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            elif request.module in {"flood_susceptibility", "flood_hazard_zonation"}:
                execution = execute_derived_map(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory,
                    next_version, task_id=str(task.id),
                )
            else:
                execution = execute_survey_module(
                    resolved, mapping(to_shape(aoi.geometry)), output_directory, next_version,
                )
        else:
            execution = adapter.execute(
                EngineExecutionContext(
                    task_id=task.id,
                    project_id=task.project_id,
                    aoi_id=task.aoi_id,
                    output_directory=output_directory,
                    operation=params.get("operation", ""),
                    products=list(params.get("products") or []),
                    parameters=dict(params.get("parameters") or {}),
                    gis_metadata=metadata,
                    result_version=next_version,
                    aoi_geometry=(
                        mapping(to_shape(aoi.geometry))
                        if (aoi := db.get(AOI, task.aoi_id)) is not None
                        else None
                    ),
                ),
                _progress,
            )
        db.refresh(task)
        if task.status == TaskStatus.CANCELED:
            db.delete(result)
            db.commit()
            return
        result.result_type = execution.result_type
        result.summary = execution.summary
        result.provenance = execution.provenance
        result.output_files = {
            key: {**entry, "path": str(relative_directory / entry["path"])}
            for key, entry in execution.output_files.items()
        }
        db.commit()
        _mark_completed(db, task, execution.summary)
    except Exception as exc:  # noqa: BLE001 - worker boundary normalizes failures
        logger.exception("Engine task failed task_id=%s", task_id)
        db.rollback()
        if result is not None and isinstance(getattr(exc, "quality_record", None), dict):
            persisted = db.get(Result, result.id)
            if persisted is not None and not persisted.output_files:
                # Progress commits may have persisted a running placeholder.
                # A failed acquisition must never leave a deliverable Result.
                db.delete(persisted)

        task = db.get(Task, task_id)
        if task is not None:
            _mark_failed(db, task, exc)


@celery_app.task(name="nova.tasks.run_engine_analysis", bind=True)
def run_engine_analysis(self, task_id: str) -> None:
    db = SessionLocal()
    try:
        execute_engine_task(db, uuid.UUID(task_id))
    finally:
        db.close()
