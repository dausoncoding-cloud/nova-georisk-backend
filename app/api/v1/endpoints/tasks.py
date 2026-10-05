"""Task status endpoints — Queued -> Running -> Completed -> Failed."""
from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.serializers import serialize_task
from app.core.entitlements import active_engine_keys, require_active_membership, require_engine_entitlement
from app.core.security import OrganizationRole, RequestContext, get_request_context, require_project_access, require_role, verify_internal_secret
from app.db.session import get_db
from app.models.project import Project
from app.models.aoi import AOI
from app.services.tasks.execution import initialize_execution, append_event, admit_task, execution_record, redact_snapshot, fingerprint, verify_events
from app.models.result import Result
from app.models.task import Task
from app.models.task import TaskStatus, TaskType
from app.schemas.common import TaskPage, TaskStatusResponse, TaskArchiveResponse

router = APIRouter(prefix="/tasks", tags=["Tasks"], dependencies=[Depends(verify_internal_secret)])


def _latest_result(db: Session, task_id: uuid.UUID) -> Result | None:
    return (
        db.query(Result)
        .filter(Result.task_id == task_id, Result.summary["status"].astext.is_distinct_from("running"))
        .order_by(Result.created_at.desc())
        .first()
    )


@router.get("", response_model=TaskPage)
def list_tasks(
    project_id: uuid.UUID | None = None,
    aoi_id: uuid.UUID | None = None,
    task_status: TaskStatus | None = Query(None, alias="status"),
    task_type: TaskType | None = None,
    engine_key: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> TaskPage:
    query = db.query(Task).join(Project, Task.project_id == Project.id)
    if not context.is_service:
        require_active_membership(db, context)
        query = query.filter(
            Project.organization_id == context.organization_id,
            Task.engine_key.in_(active_engine_keys(db, context.organization_id)),
        )
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    if aoi_id is not None:
        query = query.filter(Task.aoi_id == aoi_id)
    if task_status is not None:
        query = query.filter(Task.status == task_status)
    if task_type is not None:
        query = query.filter(Task.task_type == task_type)
    if engine_key is not None:
        query = query.filter(Task.engine_key == engine_key.strip().lower())

    total = query.with_entities(func.count(Task.id)).scalar() or 0
    tasks = query.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
    items = [serialize_task(task, _latest_result(db, task.id)) for task in tasks]
    return TaskPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> TaskStatusResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    require_active_membership(db, context)
    require_project_access(task.project, context)
    require_engine_entitlement(db, context, task.engine_key)
    return serialize_task(task, _latest_result(db, task.id))


@router.post("/{task_id}/cancel", response_model=TaskStatusResponse)
def cancel_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> TaskStatusResponse:
    task = db.query(Task).filter(Task.id == task_id).populate_existing().with_for_update().first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    require_active_membership(db, context)
    require_project_access(task.project, context)
    require_engine_entitlement(db, context, task.engine_key)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
        raise HTTPException(status_code=409, detail="Only queued or running tasks can be canceled.")
    task.status = TaskStatus.CANCELED
    task.completed_at = datetime.now(timezone.utc)
    task.error_summary = None
    if execution_record(task) is None:
        initialize_execution(task, db.get(AOI, task.aoi_id))
    try:
        append_event(task, "canceled", actor_id=context.user_id)
    except (ValueError, TypeError, KeyError):
        task.result_payload = {**(task.result_payload or {}), "execution_integrity_error": True}
    db.commit()
    if task.celery_task_id:
        try:
            from app.core.celery_app import celery_app

            celery_app.control.revoke(task.celery_task_id, terminate=False)
        except Exception:
            # The persisted canceled state is authoritative even if the broker
            # is temporarily unavailable; workers re-check it before commit.
            pass
    return serialize_task(task, _latest_result(db, task.id))


@router.post("/{task_id}/retry", response_model=TaskStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> TaskStatusResponse:
    original = db.query(Task).filter(Task.id == task_id).populate_existing().with_for_update().first()
    if original is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    require_active_membership(db, context)
    require_project_access(original.project, context)
    require_engine_entitlement(db, context, original.engine_key)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    if execution_record(original) is not None:
        try:
            verify_events(execution_record(original))
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=409, detail="Execution history is inconsistent; explicitly submit a new request.") from exc
    if original.status not in {TaskStatus.FAILED, TaskStatus.CANCELED}:
        raise HTTPException(status_code=409, detail="Only failed or canceled tasks can be retried.")
    retried = Task(
        project_id=original.project_id,
        engine_key=original.engine_key,
        aoi_id=original.aoi_id,
        task_type=original.task_type,
        status=TaskStatus.QUEUED,
        input_params=deepcopy(original.input_params),
    )
    admit_task(db, original.project)
    initialize_execution(retried, db.get(AOI, retried.aoi_id), context=context, retry_of=original.id)
    if execution_record(original) is None:
        initialize_execution(original, db.get(AOI, original.aoi_id))
    append_event(original, "retry_created", actor_id=context.user_id)
    db.add(retried)
    db.commit()
    db.refresh(retried)
    try:
        if retried.task_type == TaskType.ANALYSIS:
            from app.workers.celery_tasks import run_engine_analysis

            queued = run_engine_analysis.delay(str(retried.id))
        elif retried.task_type == TaskType.INGESTION:
            from app.workers.celery_tasks import run_flood_screening_atlas

            queued = run_flood_screening_atlas.delay(str(retried.id))
        else:
            raise RuntimeError("This task type does not have a retry dispatcher.")
        db.refresh(retried, with_for_update=True)
        if isinstance(getattr(queued, "id", None), str):
            retried.celery_task_id = queued.id
        append_event(retried, "enqueued", actor_id=context.user_id)
        db.commit()
    except Exception as exc:
        db.refresh(retried, with_for_update=True)
        if retried.status != TaskStatus.QUEUED:
            db.rollback()
            raise HTTPException(status_code=503, detail="Queue acknowledgement failed; check the persisted task status.") from exc
        retried.status = TaskStatus.FAILED
        retried.error_summary = "The retry could not be queued. Please retry later."
        retried.completed_at = datetime.now(timezone.utc)
        append_event(retried, "failed", actor_id=context.user_id)
        db.commit()
        raise HTTPException(status_code=503, detail=retried.error_summary) from exc
    return serialize_task(retried)


@router.get("/{task_id}/archive", response_model=TaskArchiveResponse)
def get_task_archive(task_id: uuid.UUID, db: Session = Depends(get_db),
                     context: RequestContext = Depends(get_request_context)) -> TaskArchiveResponse:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    require_active_membership(db, context)
    require_project_access(task.project, context)
    require_engine_entitlement(db, context, task.engine_key)
    record = execution_record(task)
    if record:
        try:
            verify_events(record)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=409, detail="Archived execution history is inconsistent.") from exc
    if record and record["parameters_sha256"] != fingerprint(task.input_params or {}):
        raise HTTPException(status_code=409, detail="Archived input fingerprint is inconsistent.")
    results = db.query(Result).filter(Result.task_id == task.id, Result.summary["status"].astext.is_distinct_from("running")).order_by(Result.version).all()
    return TaskArchiveResponse(task=serialize_task(task, results[-1] if results else None),
        submitted_parameters=redact_snapshot(task.input_params or {}),
        results=[{"id": str(result.id), "result_type": result.result_type, "version": result.version,
                  "created_at": result.created_at.isoformat()} for result in results if (result.output_files or {})],
        limitations=["Legacy jobs may have no historical actor/AOI/code fingerprint; missing history is never invented.",
                     "Consistency hashes are not cryptographic proof against privileged database administrators."])
