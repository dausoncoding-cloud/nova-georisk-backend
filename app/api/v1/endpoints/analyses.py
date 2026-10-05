"""Engine-neutral submission and capability contracts."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from app.api.v1.serializers import serialize_task
from app.core.entitlements import require_active_membership, require_engine_entitlement
from app.core.security import (
    OrganizationRole,
    RequestContext,
    get_request_context,
    require_project_access,
    require_role,
    verify_internal_secret,
)
from app.db.session import get_db
from app.models.aoi import AOI
from app.models.project import Project
from app.models.task import Task, TaskStatus, TaskType
from app.platform.engines import get_engine_adapter
from app.schemas.analyses import AnalysisSubmitRequest, AnalysisSubmitResponse, EngineExecutionContract
from app.schemas.source_bindings import SourceBoundAnalysisRequest, SourceBindingValidationResponse
from app.services.source_data.bindings import EXECUTABLE_MODULES, binding_contract, resolve_bindings
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.boundaries import revalidate_boundary_aoi

router = APIRouter(prefix="/analyses", tags=["Analyses"], dependencies=[Depends(verify_internal_secret)])


@router.get("/source-bindings/contract")
def get_source_binding_contract(
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> dict:
    require_active_membership(db, context)
    require_engine_entitlement(db, context, "firris")
    return binding_contract()


def _validate_source_request(payload: SourceBoundAnalysisRequest, db: Session, context: RequestContext):
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    if project.engine_key != "firris":
        raise HTTPException(status_code=409, detail="Source-bound modules require a FIRRIS project.")
    require_engine_entitlement(db, context, "firris")
    aoi = db.get(AOI, payload.aoi_id)
    if aoi is None or aoi.project_id != project.id:
        raise HTTPException(status_code=404, detail="AOI not found for this project.")
    try:
        revalidate_boundary_aoi(db, aoi)
        return resolve_bindings(db, payload, aoi_geometry=mapping(to_shape(aoi.geometry)))
    except SourceNotReady as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/source-bindings/validate", response_model=SourceBindingValidationResponse)
def validate_source_bindings(
    payload: SourceBoundAnalysisRequest,
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> SourceBindingValidationResponse:
    _validate_source_request(payload, db, context)
    executable = payload.module in EXECUTABLE_MODULES
    return SourceBindingValidationResponse(
        module=payload.module, source_ids=payload.sources, analysis_ready=True, executable=executable,
        reason=None if executable else "Source binding is valid, but the reviewed source-to-formula adapter is not operational.",
    )


@router.post("/source-bound", response_model=AnalysisSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_source_bound_analysis(
    payload: SourceBoundAnalysisRequest,
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> AnalysisSubmitResponse:
    bindings = _validate_source_request(payload, db, context)
    if payload.module not in EXECUTABLE_MODULES:
        raise HTTPException(status_code=422, detail="This FIRRIS module has no validated source-to-formula adapter yet.")
    source_snapshot = {
        role: {"dataset_id": str(source.dataset.id), "sha256": source.manifest.sha256.lower(),
               "source_version": source.dataset.created_at.isoformat() if source.dataset.created_at else None,
               "reviewed_at": source.evidence.get("reviewed_at")}
        for role, source in bindings.sources.items()
    }
    if payload.module == "flood_change":
        from app.services.source_data.change import comparison_source_fingerprint
        for role, source in bindings.sources.items():
            source_snapshot[role]["comparison_manifest_sha256"] = comparison_source_fingerprint(source)
    result_snapshot = {role: result.lineage() for role, result in bindings.upstream.items()}
    task = Task(
        project_id=payload.project_id, engine_key="firris", aoi_id=payload.aoi_id,
        task_type=TaskType.ANALYSIS, status=TaskStatus.QUEUED,
        input_params={"operation": f"source_bound_{payload.module}", "source_binding": payload.model_dump(mode="json"), "source_snapshot": source_snapshot, "result_snapshot": result_snapshot},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    from app.workers.celery_tasks import run_engine_analysis
    try:
        queued = run_engine_analysis.delay(str(task.id))
        if isinstance(getattr(queued, "id", None), str):
            task.celery_task_id = queued.id
        db.commit()
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.error_summary = "The analysis job could not be queued. Please retry."
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=503, detail=task.error_summary) from exc
    return AnalysisSubmitResponse(task=serialize_task(task))


@router.get("/engines/{engine_key}", response_model=EngineExecutionContract)
def get_execution_contract(
    engine_key: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> EngineExecutionContract:
    require_active_membership(db, context)
    require_engine_entitlement(db, context, engine_key)
    try:
        adapter = get_engine_adapter(engine_key)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail="Engine execution is not available.") from exc
    return EngineExecutionContract.model_validate(adapter.contract())


@router.post("", response_model=AnalysisSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_analysis(
    payload: AnalysisSubmitRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AnalysisSubmitResponse:
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    aoi = db.get(AOI, payload.aoi_id)
    if aoi is None or aoi.project_id != project.id:
        raise HTTPException(status_code=404, detail="AOI not found for this project.")
    try:
        revalidate_boundary_aoi(db, aoi)
    except SourceNotReady as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        get_engine_adapter(project.engine_key)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail="Project engine execution is not available.") from exc
    if payload.gis_metadata.crs.strip().upper() != project.crs.strip().upper():
        raise HTTPException(status_code=422, detail="GIS metadata CRS must match the project CRS.")
    if project.engine_key == "firris" and payload.parameters.workflow is not None:
        unsupported = sorted(product.value for product in payload.products if product.value not in {"flood_extent", "flood_probability"})
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail=f"The FIRRIS satellite workflow cannot produce these products without sourced inputs: {', '.join(unsupported)}.",
            )

    task = Task(
        project_id=project.id,
        engine_key=project.engine_key,
        aoi_id=aoi.id,
        task_type=TaskType.ANALYSIS,
        status=TaskStatus.QUEUED,
        input_params=payload.model_dump(mode="json"),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    from app.workers.celery_tasks import run_engine_analysis

    try:
        queued = run_engine_analysis.delay(str(task.id))
        if isinstance(getattr(queued, "id", None), str):
            task.celery_task_id = queued.id
        db.commit()
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.error_summary = "The analysis job could not be queued. Please retry."
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=503, detail=task.error_summary) from exc
    return AnalysisSubmitResponse(task=serialize_task(task))
