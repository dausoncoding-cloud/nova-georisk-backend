"""Protected FIRRIS source handoff: validate first, then register immutable bytes."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.artifact_storage import ArtifactStorageError, require_artifact_storage_ready
from app.core.entitlements import require_active_membership, require_engine_entitlement
from app.core.security import (
    OrganizationRole, RequestContext, get_request_context, require_project_access,
    require_role, verify_internal_secret,
)
from app.db.session import get_db
from app.models.dataset import Dataset
from app.models.project import Project
from app.schemas.source_data import SourceDatasetManifest, SourceDatasetRegistered, SourceDatasetValidation, SourceReadinessReview, SourceReadinessStatus
from app.services.source_data.catalogue import get_catalogue
from app.services.source_data.readiness import SourceNotReady, load_registered_source
from app.services.source_data.validators import MAX_BYTES, SourceDataValidationError, validate_source_data

router = APIRouter(prefix="/source-datasets", tags=["Source datasets"], dependencies=[Depends(verify_internal_secret)])


def _authorize(db: Session, context: RequestContext, project_id: uuid.UUID) -> None:
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    if project.engine_key != "firris":
        raise HTTPException(status_code=409, detail="Source-data ingestion requires a FIRRIS project.")
    require_engine_entitlement(db, context, "firris")


async def _validated(raw: str, file: UploadFile, db: Session, context: RequestContext):
    try:
        manifest = SourceDatasetManifest.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid source-data manifest.") from exc
    _authorize(db, context, manifest.project_id)
    data = await file.read(MAX_BYTES + 1)
    try:
        report = validate_source_data(manifest, data, file.filename or "")
    except SourceDataValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return manifest, report, data


@router.get("/catalogue")
def catalogue(db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context)) -> dict:
    require_active_membership(db, context)
    return get_catalogue()


@router.post("/validate", response_model=SourceDatasetValidation)
async def validate_upload(
    manifest: str = Form(...), file: UploadFile = File(...),
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> SourceDatasetValidation:
    _, report, _ = await _validated(manifest, file, db, context)
    return report


@router.post("", response_model=SourceDatasetRegistered, status_code=status.HTTP_201_CREATED)
async def register_upload(
    manifest: str = Form(...), file: UploadFile = File(...),
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> SourceDatasetRegistered:
    parsed, report, data = await _validated(manifest, file, db, context)
    try:
        root = require_artifact_storage_ready()
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=503, detail="Source-data storage is unavailable.") from exc
    extension = {"csv": ".csv", "geojson": ".geojson", "geotiff": ".tif"}[report.format]
    dataset_id = uuid.uuid4()
    directory = root / "source-datasets" / str(parsed.project_id)
    target = directory / f"{dataset_id}{extension}"
    temporary = directory / f".{dataset_id}.upload"
    record = Dataset(
        id=dataset_id, project_id=parsed.project_id,
        source_collection=parsed.source_id, product_type=parsed.category,
        acquisition_start=parsed.temporal_coverage.start,
        acquisition_end=parsed.temporal_coverage.end,
        spatial_resolution_m=(parsed.spatial_resolution.x if parsed.spatial_resolution and parsed.spatial_resolution.unit == "m" else None),
        processed_asset_ref=str(target),
        metadata_json={"source_manifest": parsed.model_dump(mode="json"), "validation": report.model_dump(mode="json")},
    )
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return SourceDatasetRegistered(**report.model_dump(), dataset_id=dataset_id)


@router.post("/{dataset_id}/approve", response_model=SourceReadinessStatus)
def approve_source_dataset(
    dataset_id: uuid.UUID, review: SourceReadinessReview,
    db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> SourceReadinessStatus:
    if context.is_service:
        raise HTTPException(status_code=403, detail="A NOVA organization administrator must approve source readiness.")
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN)
    record = db.get(Dataset, dataset_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source dataset not found.")
    _authorize(db, context, record.project_id)
    try:
        source = load_registered_source(db, dataset_id, record.project_id, require_ready=False)
    except SourceNotReady as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    evidence = {
        "analysis_ready": True,
        "sha256": source.manifest.sha256.lower(),
        "reviewed_by": str(context.user_id),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "evidence_refs": review.evidence_refs,
        "checks_complete": True,
        "checks": review.model_dump(exclude={"evidence_refs"}),
    }
    record.metadata_json = {**record.metadata_json, "readiness": evidence}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(record, "metadata_json")
    db.commit()
    return SourceReadinessStatus(dataset_id=dataset_id, analysis_ready=True, sha256=evidence["sha256"])


@router.post("/{dataset_id}/revoke", response_model=SourceReadinessStatus)
def revoke_source_dataset(
    dataset_id: uuid.UUID, db: Session = Depends(get_db), context: RequestContext = Depends(get_request_context),
) -> SourceReadinessStatus:
    if context.is_service:
        raise HTTPException(status_code=403, detail="A NOVA organization administrator must revoke source readiness.")
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN)
    record = db.get(Dataset, dataset_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source dataset not found.")
    _authorize(db, context, record.project_id)
    metadata = record.metadata_json or {}
    metadata["readiness"] = {"analysis_ready": False, "revoked_by": str(context.user_id), "revoked_at": datetime.now(timezone.utc).isoformat()}
    record.metadata_json = metadata
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(record, "metadata_json")
    db.commit()
    return SourceReadinessStatus(dataset_id=dataset_id, analysis_ready=False, sha256=metadata.get("source_manifest", {}).get("sha256", ""))
