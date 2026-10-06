"""
Celery task shells for long-running GEE/geoprocessing jobs.

Each task follows the same pattern: load the Task row, flip its status
Queued -> Running, do the work via the relevant service, write the
Result row(s), flip status -> Completed/Failed.
"""
from __future__ import annotations

import logging
import shutil
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
from app.services.tasks.execution import (append_event, execution_record, claim_task,
    validate_execution, validate_workload, validate_source_snapshots)
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from celery.worker.request import Request
from celery.exceptions import Ignore, Reject, Retry
from billiard.einfo import ExceptionWithTraceback

logger = logging.getLogger(__name__)


def persist_worker_failure(task_id, error):
    """Parent-process failure bridge for a hard timeout or lost worker child.

    A database/broker outage still requires operational recovery; this callback
    never invents a completion or silently reuses a partially produced result.
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == uuid.UUID(str(task_id))).with_for_update().first()
        if task is None or task.engine_key != "firris" or task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
            return
        reserved = db.query(Result).filter(Result.task_id == task.id,
            Result.summary["status"].astext == "running").all()
        paths = [Path(str(task.project_id)) / str(task.aoi_id) / str(result.id) for result in reserved]
        for result in reserved:
            db.delete(result)
        _mark_failed(db, task, error)
        from app.core.config import get_settings
        root = Path(get_settings().output_storage_dir)
        for relative in paths:
            directory = root / relative
            if directory.is_dir():
                shutil.rmtree(directory)
    except Exception:
        db.rollback()
        logger.exception("Could not persist worker failure task_id=%s", task_id)
    finally:
        db.close()


class FIRRISRequest(Request):
    """Keep the authoritative database lifecycle aligned with Celery failures."""
    def on_timeout(self, soft, timeout):
        try:
            return super().on_timeout(soft, timeout)
        finally:
            if not soft and self.args:
                persist_worker_failure(self.args[0], RuntimeError("Worker hard time limit exceeded"))

    def on_failure(self, exc_info, send_failed_event=True, return_ok=False):
        try:
            return super().on_failure(exc_info, send_failed_event, return_ok)
        finally:
            error = exc_info.exception
            if isinstance(error, ExceptionWithTraceback):
                error = error.exc
            if self.args and not isinstance(error, (Ignore, Reject, Retry)):
                persist_worker_failure(self.args[0], error)


def _mark_running(db, task: Task) -> None:
    if task.status == TaskStatus.CANCELED:
        return
    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now(timezone.utc)
    task.error_summary = None
    append_event(task, "started")
    db.commit()


def _mark_completed(db, task: Task, result_payload: dict) -> None:
    db.refresh(task)
    if task.status == TaskStatus.CANCELED:
        return
    task.status = TaskStatus.COMPLETED
    task.progress_pct = 100
    record = execution_record(task)
    task.result_payload = {**result_payload, **({"execution_record": record} if record else {})}
    task.completed_at = datetime.now(timezone.utc)
    append_event(task, "completed")
    db.commit()


def _mark_failed(db, task: Task, error: Exception) -> None:
    db.refresh(task, with_for_update=True)
    if task.status in {TaskStatus.CANCELED, TaskStatus.COMPLETED, TaskStatus.FAILED}:
        return
    task.status = TaskStatus.FAILED
    # Raw exceptions remain server-side for diagnosis.  API responses expose
    # only this stable, non-sensitive summary.
    task.error_message = str(error)
    if isinstance(getattr(error, "quality_record", None), dict):
        task.result_payload = {**(task.result_payload or {}), "quality": error.quality_record}
    task.error_summary = "Analysis execution failed. Please retry or contact support with the request ID."
    try:
        append_event(task, "failed")
    except (ValueError, TypeError, KeyError):
        # Preserve the rejected record in storage; expose only an integrity flag.
        task.result_payload = {**(task.result_payload or {}), "execution_integrity_error": True}
    task.completed_at = datetime.now(timezone.utc)
    db.commit()


@celery_app.task(name="nova.tasks.run_flood_screening_atlas", bind=True,
                 Request="app.workers.celery_tasks:FIRRISRequest")
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
    output_directory = None
    try:
        task = claim_task(db, uuid.UUID(task_id))
        if task is None:
            return
        validate_execution(task, db.get(AOI, task.aoi_id))
        validate_workload(task.input_params or {})
        _mark_running(db, task)

        params = task.input_params or {}
        required = ["project_id", "aoi_id", "aoi_geometry", "target_start", "target_end", "baseline_start", "baseline_end"]
        missing = [k for k in required if k not in params]
        if missing:
            raise ValueError(f"Missing required input_params: {missing}")

        def _progress(pct: int) -> None:
            db.refresh(task, with_for_update=True)
            if task.status == TaskStatus.RUNNING:
                next_pct = max(task.progress_pct, max(0, min(99, int(pct))))
                if task.progress_pct != next_pct:
                    task.progress_pct = next_pct
                    append_event(task, "progress")
            db.commit()

        # Serialize version reservation per persisted AOI across worker processes.
        db.query(AOI).filter(AOI.id == task.aoi_id).with_for_update().first()
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
        db.commit()
        result_id = result.id
        output_root = require_artifact_storage_ready()
        output_directory = output_root / str(task.project_id) / str(task.aoi_id) / str(result_id)
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

        db.expire_all()
        db.refresh(task, with_for_update=True)
        if task.status != TaskStatus.RUNNING:
            persisted = db.get(Result, result_id)
            if persisted is not None:
                db.delete(persisted)
            db.commit()
            shutil.rmtree(output_directory, ignore_errors=True)
            return
        validate_execution(task, db.get(AOI, task.aoi_id))
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
                db.delete(persisted_result)
                db.commit()
        if task:
            _mark_failed(db, task, exc)
        if output_directory:
            shutil.rmtree(output_directory, ignore_errors=True)
    finally:
        db.close()


def execute_engine_task(db, task_id: uuid.UUID) -> None:
    """Execute one persisted engine job; kept session-injectable for integration tests."""
    task = claim_task(db, task_id)
    if task is None:
        return
    result = None
    output_directory = None
    try:
        validate_execution(task, db.get(AOI, task.aoi_id))
        validate_workload(task.input_params or {})
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

        db.query(AOI).filter(AOI.id == task.aoi_id).with_for_update().first()
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
        db.commit()  # Persist the reserved version before releasing its AOI lock.
        result_id = result.id

        relative_directory = Path(str(task.project_id)) / str(task.aoi_id) / str(result.id)
        output_directory = require_artifact_storage_ready() / relative_directory

        def _progress(value: int) -> None:
            db.refresh(task, with_for_update=True)
            if task.status == TaskStatus.RUNNING:
                next_pct = max(task.progress_pct, max(0, min(99, int(value))))
                if next_pct != task.progress_pct:
                    task.progress_pct = next_pct
                    append_event(task, "progress")
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
            validate_source_snapshots(resolved, params)
            _progress(10)
            db.refresh(task, with_for_update=True)
            if task.status == TaskStatus.RUNNING:
                append_event(task, "sources_revalidated")
            db.commit()
            from app.services.source_data.bindings import BUNDLE4_MODULES, EVIDENCE_MODULES
            if request.module in EVIDENCE_MODULES:
                from app.services.source_data.evidence_products import execute_evidence_products
                execution = execute_evidence_products(resolved, mapping(to_shape(aoi.geometry)), output_directory,
                                                      next_version, task_id=str(task.id))
            elif request.module in BUNDLE4_MODULES:
                from app.services.source_data.bundle4 import execute_bundle4
                execution = execute_bundle4(resolved, mapping(to_shape(aoi.geometry)), output_directory,
                                            next_version, task_id=str(task.id))
            elif request.module == "satellite_preprocessing":
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
        db.expire_all()
        db.refresh(task, with_for_update=True)
        if task.status != TaskStatus.RUNNING:
            persisted = db.get(Result, result_id)
            if persisted is not None:
                db.delete(persisted)
            db.commit()
            if output_directory and output_directory.is_dir():
                shutil.rmtree(output_directory)
            return
        db.refresh(aoi)
        validate_execution(task, aoi)
        if "source_binding" in params:
            published = resolve_bindings(db, request, aoi_geometry=mapping(to_shape(aoi.geometry)))
            validate_source_snapshots(published, params)
            append_event(task, "sources_revalidated")
        result.result_type = execution.result_type
        result.summary = execution.summary
        result.provenance = execution.provenance
        task.status = TaskStatus.COMPLETED
        task.progress_pct = 100
        task.completed_at = datetime.now(timezone.utc)
        record = execution_record(task)
        task.result_payload = {**execution.summary, "execution_record": record}
        append_event(task, "completed")
        from app.services.tasks.archive import completion_archive
        scientific_outputs = dict(execution.output_files)
        scientific_outputs["execution_archive"] = completion_archive(output_directory, task, result, scientific_outputs)
        result.output_files = {
            key: {**entry, "path": str(relative_directory / entry["path"])}
            for key, entry in scientific_outputs.items()
        }
        db.commit()
    except Exception as exc:  # noqa: BLE001 - worker boundary normalizes failures
        logger.exception("Engine task failed task_id=%s", task_id)
        db.rollback()
        if result is not None:
            persisted = db.get(Result, result.id)
            if persisted is not None and not persisted.output_files:
                # A failed job must never leave its reserved/running Result.
                db.delete(persisted)

        task = db.get(Task, task_id)
        if task is not None:
            _mark_failed(db, task, exc)
        if output_directory and output_directory.is_dir():
            shutil.rmtree(output_directory)


@celery_app.task(name="nova.tasks.run_engine_analysis", bind=True,
                 Request="app.workers.celery_tasks:FIRRISRequest")
def run_engine_analysis(self, task_id: str) -> None:
    db = SessionLocal()
    try:
        execute_engine_task(db, uuid.UUID(task_id))
    finally:
        db.close()
