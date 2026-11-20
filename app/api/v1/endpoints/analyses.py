"""Engine-neutral submission and capability contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
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
from app.core.config import get_settings
from app.core.rate_limit import FixedWindowRateLimiter, get_preflight_limiter
from app.schemas.analyses import (AnalysisPreflightResponse, AnalysisPreflightTrendPasses, AnalysisSubmitRequest, AnalysisSubmitResponse,
                                  EngineExecutionContract, SatelliteSourceConfig)
from app.services.firris import preflight as firris_preflight
from app.schemas.source_bindings import SourceBoundAnalysisRequest, SourceBindingValidationResponse
from app.services.source_data.bindings import EXECUTABLE_MODULES, binding_contract, resolve_bindings
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.boundaries import revalidate_boundary_aoi

from app.services.tasks.execution import initialize_execution, append_event, admit_task, validate_workload
from app.services.billing import refunds as billing_refunds
from app.services.billing import submission as billing

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
        raise HTTPException(status_code=409, detail="Source-bound modules are only available in FRRIS projects.")
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
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> AnalysisSubmitResponse:
    idempotency_key = billing.validate_key(idempotency_key)
    fingerprint = billing.request_fingerprint("source-bound", payload.model_dump(mode="json"))
    bindings = _validate_source_request(payload, db, context)
    if payload.module not in EXECUTABLE_MODULES:
        raise HTTPException(status_code=422, detail="This FRRIS module has no validated source-to-formula adapter yet.")
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
    from app.services.source_data.change import comparison_source_fingerprint
    for role, source in bindings.sources.items():
        source_snapshot[role]["manifest_sha256"] = comparison_source_fingerprint(source)
    result_snapshot = {role: result.lineage() for role, result in bindings.upstream.items()}
    task = Task(
        project_id=payload.project_id, engine_key="firris", aoi_id=payload.aoi_id,
        task_type=TaskType.ANALYSIS, status=TaskStatus.QUEUED,
        input_params={"operation": f"source_bound_{payload.module}", "source_binding": payload.model_dump(mode="json"), "source_snapshot": source_snapshot, "result_snapshot": result_snapshot},
    )
    try:
        validate_workload(task.input_params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project = db.get(Project, task.project_id)
    admit_task(db, project)
    replayed = billing.replay_or_none(db, context, idempotency_key, "source-bound", fingerprint)
    if replayed is not None:
        return AnalysisSubmitResponse(task=serialize_task(replayed))
    charge = billing.SubmissionCharge.reserve(db, context, "firris")
    initialize_execution(task, db.get(AOI, task.aoi_id), context=context)
    db.add(task)
    charge.charge(db, task)
    billing.remember_key(db, context, idempotency_key, "source-bound", fingerprint, task)
    db.commit()
    db.refresh(task)
    from app.workers.celery_tasks import run_engine_analysis
    try:
        queued = run_engine_analysis.delay(str(task.id))
        db.refresh(task, with_for_update=True)
        if isinstance(getattr(queued, "id", None), str):
            task.celery_task_id = queued.id
        append_event(task, "enqueued", actor_id=context.user_id)
        db.commit()
    except Exception as exc:
        db.refresh(task, with_for_update=True)
        if task.status != TaskStatus.QUEUED:
            db.rollback()
            raise HTTPException(status_code=503, detail="Queue acknowledgement failed; check the persisted task status.") from exc
        task.status = TaskStatus.FAILED
        task.error_summary = "The analysis job could not be queued. Please retry."
        task.completed_at = datetime.now(timezone.utc)
        append_event(task, "failed", actor_id=context.user_id)
        billing_refunds.refund_failed_task(db, task, cause="queue_failure")
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


def _authorized_submission(db: Session, context: RequestContext, payload: AnalysisSubmitRequest) -> tuple[Project, AOI]:
    """Membership, role, organization scope, entitlement and request-shape checks shared by preflight and submit."""
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
                detail=f"The FRRIS satellite workflow cannot produce these products without sourced inputs: {', '.join(unsupported)}.",
            )
    return project, aoi


def _gee_source(project: Project, payload: AnalysisSubmitRequest) -> SatelliteSourceConfig | None:
    workflow = payload.parameters.workflow
    if project.engine_key == "firris" and workflow is not None and workflow.source.provider == "gee":
        return workflow.source
    return None


def _run_preflight(aoi: AOI, source: SatelliteSourceConfig) -> AnalysisPreflightResponse:
    try:
        return firris_preflight.run_preflight(aoi_geometry=mapping(to_shape(aoi.geometry)), source=source,
                                              timeout=get_settings().firris_preflight_timeout_seconds)
    except firris_preflight.PreflightUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "60"}) from exc


@router.post("/preflight", response_model=AnalysisPreflightResponse)
def preflight_analysis(
    payload: AnalysisSubmitRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
    limiter: FixedWindowRateLimiter = Depends(get_preflight_limiter),
) -> AnalysisPreflightResponse:
    """Metadata-only availability check before the FRRIS satellite analysis is submitted. Never creates a task or result."""
    project, aoi = _authorized_submission(db, context, payload)
    settings = get_settings()
    if not (limiter.allow(f"firris:preflight:user:{context.user_id}", settings.firris_preflight_per_user_per_minute)
            and limiter.allow(f"firris:preflight:org:{context.organization_id}", settings.firris_preflight_per_organization_per_minute)):
        raise HTTPException(status_code=429, detail="Too many availability checks. Please wait a minute and try again.",
                            headers={"Retry-After": "60"})
    source = _gee_source(project, payload)
    if source is None:
        raise HTTPException(status_code=422, detail="Availability checks apply to FRRIS satellite (Earth Engine) analyses.")
    response = _run_preflight(aoi, source)
    trend = payload.parameters.workflow.context.trend_analysis
    if trend is not None and not response.blocking:  # Trend Analysis: pass count of the series window (never blocks)
        field, warnings = firris_preflight.trend_sar_preflight(
            mapping(to_shape(aoi.geometry)), response, trend, target_last=source.target_period.end - timedelta(days=1),
            baseline_first=source.baseline_period.start, timeout=settings.firris_preflight_timeout_seconds)
        response = response.model_copy(update={"trend_sar_passes": AnalysisPreflightTrendPasses(**field) if field else None,
                                               "warnings": [*response.warnings, *warnings]})
    return response


@router.post("", response_model=AnalysisSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_analysis(
    payload: AnalysisSubmitRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> AnalysisSubmitResponse:
    idempotency_key = billing.validate_key(idempotency_key)
    fingerprint = billing.request_fingerprint("analyses", payload.model_dump(mode="json"))
    project, aoi = _authorized_submission(db, context, payload)
    # A retried request returns the first task before re-running the (slow) preflight; rechecked under lock below.
    replayed = billing.replay_or_none(db, context, idempotency_key, "analyses", fingerprint)
    if replayed is not None:
        return AnalysisSubmitResponse(task=serialize_task(replayed))
    # Server-side enforcement of the preflight blocking rules (never rely on the UI). Metadata only.
    warnings = []
    source = _gee_source(project, payload)
    if source is not None:
        checked = _run_preflight(aoi, source)
        if checked.blocking:
            raise HTTPException(status_code=422, detail=" ".join(issue.message for issue in checked.blocking))
        warnings = checked.warnings

    task = Task(
        project_id=project.id,
        engine_key=project.engine_key,
        aoi_id=aoi.id,
        task_type=TaskType.ANALYSIS,
        status=TaskStatus.QUEUED,
        input_params=payload.model_dump(mode="json"),
    )
    try:
        validate_workload(task.input_params)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project = db.get(Project, task.project_id)
    admit_task(db, project)
    replayed = billing.replay_or_none(db, context, idempotency_key, "analyses", fingerprint)
    if replayed is not None:
        return AnalysisSubmitResponse(task=serialize_task(replayed))
    charge = billing.SubmissionCharge.reserve(db, context, project.engine_key)
    initialize_execution(task, db.get(AOI, task.aoi_id), context=context)
    db.add(task)
    charge.charge(db, task)
    billing.remember_key(db, context, idempotency_key, "analyses", fingerprint, task)
    db.commit()
    db.refresh(task)

    from app.workers.celery_tasks import run_engine_analysis

    try:
        queued = run_engine_analysis.delay(str(task.id))
        db.refresh(task, with_for_update=True)
        if isinstance(getattr(queued, "id", None), str):
            task.celery_task_id = queued.id
        append_event(task, "enqueued", actor_id=context.user_id)
        db.commit()
    except Exception as exc:
        db.refresh(task, with_for_update=True)
        if task.status != TaskStatus.QUEUED:
            db.rollback()
            raise HTTPException(status_code=503, detail="Queue acknowledgement failed; check the persisted task status.") from exc
        task.status = TaskStatus.FAILED
        task.error_summary = "The analysis job could not be queued. Please retry."
        task.completed_at = datetime.now(timezone.utc)
        append_event(task, "failed", actor_id=context.user_id)
        billing_refunds.refund_failed_task(db, task, cause="queue_failure")
        db.commit()
        raise HTTPException(status_code=503, detail=task.error_summary) from exc
    return AnalysisSubmitResponse(task=serialize_task(task), preflight_warnings=warnings)
