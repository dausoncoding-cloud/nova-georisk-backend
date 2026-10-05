"""
Ingestion trigger endpoints. Unlike the FIRRIS/validation/maps
endpoints (synchronous pure-math), generating a screening atlas
genuinely takes a while (Earth Engine thumbnail export for ~15
layers), so this creates a Task row and dispatches a Celery job,
returning immediately — the caller polls `GET /tasks/{id}`
(app/api/v1/endpoints/tasks.py) exactly as it would for any other
async job in this engine.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app.core.security import (
    OrganizationRole,
    RequestContext,
    get_request_context,
    require_project_access,
    require_role,
    verify_internal_secret,
)
from app.core.entitlements import require_active_membership, require_engine_entitlement
from app.db.session import get_db
from app.models.aoi import AOI
from app.models.project import Project
from app.models.task import Task, TaskStatus, TaskType
from app.schemas.ingestion import ScreeningAtlasRequest, TaskTriggerResponse

from app.services.tasks.execution import initialize_execution, append_event, admit_task, validate_workload

router = APIRouter(prefix="/ingestion", tags=["Ingestion"], dependencies=[Depends(verify_internal_secret)])


@router.post("/screening-atlas", response_model=TaskTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
def trigger_screening_atlas(
    payload: ScreeningAtlasRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> TaskTriggerResponse:
    """
    Starts a flood screening atlas job for the given project's AOI.
    Works for any project/AOI — nothing here is specific to any one
    location; the AOI's own stored geometry is what gets analyzed.
    """
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    if project.engine_key != "firris":
        raise HTTPException(status_code=409, detail="Screening atlas requires a FIRRIS project.")
    require_engine_entitlement(db, context, "firris")

    aoi = db.get(AOI, payload.aoi_id)
    if aoi is None or aoi.project_id != payload.project_id:
        raise HTTPException(status_code=404, detail="AOI not found for this project.")

    aoi_geometry = mapping(to_shape(aoi.geometry))

    task = Task(
        project_id=payload.project_id,
        engine_key=project.engine_key,
        aoi_id=payload.aoi_id,
        task_type=TaskType.INGESTION,
        status=TaskStatus.QUEUED,
        input_params={
            "project_id": str(payload.project_id),
            "aoi_id": str(payload.aoi_id),
            "aoi_geometry": aoi_geometry,
            "target_start": payload.target_start.isoformat(),
            "target_end": payload.target_end.isoformat(),
            "baseline_start": payload.baseline_start.isoformat(),
            "baseline_end": payload.baseline_end.isoformat(),
        },
    )
    try:
        validate_workload(task.input_params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    admit_task(db, project)
    initialize_execution(task, aoi, context=context)
    db.add(task)
    db.commit()
    db.refresh(task)

    # Imported here so this module (and the router that imports it) never
    # requires Celery/GEE to be importable just to register API routes.
    from app.workers.celery_tasks import run_flood_screening_atlas

    try:
        celery_result = run_flood_screening_atlas.delay(str(task.id))
        db.refresh(task, with_for_update=True)
        celery_task_id = getattr(celery_result, "id", None)
        if isinstance(celery_task_id, str):
            task.celery_task_id = celery_task_id
        append_event(task, "enqueued", actor_id=context.user_id)
        db.commit()
    except Exception:
        db.refresh(task, with_for_update=True)
        if task.status != TaskStatus.QUEUED:
            db.rollback()
            raise HTTPException(status_code=503, detail="Queue acknowledgement failed; check the persisted task status.")
        task.status = TaskStatus.FAILED
        task.error_summary = "The atlas job could not be queued. Please retry."
        append_event(task, "failed", actor_id=context.user_id)
        db.commit()
        raise HTTPException(status_code=503, detail=task.error_summary)

    return TaskTriggerResponse(task_id=task.id, status=task.status.value)
