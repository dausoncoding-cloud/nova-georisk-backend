"""Project endpoints — Doc 0 step 2 "Create / Open Project"."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.serializers import serialize_aoi
from app.core.entitlements import active_engine_keys, require_active_membership, require_engine_entitlement
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
from app.models.identity import LEGACY_ORGANIZATION_ID, Organization
from app.models.project import Project
from app.models.platform import Engine
from app.models.result import Result
from app.models.task import Task
from app.schemas.common import AOIPage

router = APIRouter(prefix="/projects", tags=["Projects"], dependencies=[Depends(verify_internal_secret)])


class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None
    crs: str = "EPSG:4326"
    analysis_module: str | None = None
    engine_key: str | None = None

    @model_validator(mode="after")
    def consistent_engine_aliases(self) -> "ProjectCreateRequest":
        if (
            self.engine_key
            and self.analysis_module
            and self.engine_key.strip().lower() != self.analysis_module.strip().lower()
        ):
            raise ValueError("engine_key and legacy analysis_module must identify the same engine.")
        return self


class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    crs: str
    analysis_module: str
    engine_key: str
    organization_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    crs: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def has_update(self) -> "ProjectUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one project field must be supplied.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Project name cannot be null.")
        if "crs" in self.model_fields_set and self.crs is None:
            raise ValueError("Project CRS cannot be null.")
        return self


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> Project:
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    organization_id = context.organization_id or LEGACY_ORGANIZATION_ID
    organization = db.get(Organization, organization_id)
    if organization is None and context.is_service:
        organization = Organization(
            id=LEGACY_ORGANIZATION_ID,
            name="Legacy organization",
            slug="legacy",
        )
        db.add(organization)
        db.flush()
    elif organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")

    requested_engine_key = (payload.engine_key or payload.analysis_module or "firris").strip().lower()
    if requested_engine_key == "firas":
        requested_engine_key = "firris"
    engine = db.get(Engine, requested_engine_key)
    if engine is None or not engine.enabled:
        raise HTTPException(status_code=409, detail="Requested engine is not available.")
    require_engine_entitlement(db, context, requested_engine_key)
    project = Project(
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        crs=payload.crs,
        engine_key=engine.key,
        analysis_module=engine.name,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)

    if "name" in payload.model_fields_set:
        project.name = payload.name.strip()
        if not project.name:
            raise HTTPException(status_code=422, detail="Project name cannot be empty.")
    if "description" in payload.model_fields_set:
        project.description = payload.description
    if "crs" in payload.model_fields_set:
        project.crs = payload.crs.strip()
        if not project.crs:
            raise HTTPException(status_code=422, detail="Project CRS cannot be empty.")
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> Response:
    """Delete only an empty project; analysis history is never cascaded implicitly."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN)

    has_dependents = any(
        (
            db.query(AOI.id).filter(AOI.project_id == project.id).first(),
            db.query(Task.id).filter(Task.project_id == project.id).first(),
            db.query(Result.id).filter(Result.project_id == project.id).first(),
        )
    )
    if has_dependents:
        raise HTTPException(
            status_code=409,
            detail="Project has AOIs, jobs, or results and cannot be deleted.",
        )
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> list[Project]:
    query = db.query(Project)
    if not context.is_service:
        require_active_membership(db, context)
        permitted_engines = active_engine_keys(db, context.organization_id)
        query = query.filter(
            Project.organization_id == context.organization_id,
            Project.engine_key.in_(permitted_engines),
        )
    return query.order_by(Project.created_at.desc()).all()


@router.get("/{project_id}/aois", response_model=AOIPage)
def list_project_aois(
    project_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AOIPage:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)

    base = db.query(AOI).filter(AOI.project_id == project_id)
    total = db.query(func.count(AOI.id)).filter(AOI.project_id == project_id).scalar() or 0
    items = base.order_by(AOI.created_at.desc()).offset(offset).limit(limit).all()
    return AOIPage(items=[serialize_aoi(aoi) for aoi in items], total=total, limit=limit, offset=offset)
