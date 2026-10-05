"""
AOI endpoints — Doc 0 step 3 "Define Area of Interest".

Accepts a drawn/uploaded AOI geometry, validates it, computes the
system stats (area/hectares/km²/perimeter), and persists it against
a project. Actual raster/vector clipping against GEE happens later in
the ingestion service (app/services/gee/ingestion.py) once a dataset
request references this AOI.
"""
from __future__ import annotations

import uuid
import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from pyogrio.errors import DataSourceError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from sqlalchemy.orm import Session

from app.api.v1.serializers import serialize_aoi
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
from app.models.dataset import Dataset
from app.models.project import Project
from app.models.result import Result
from app.models.task import Task
from app.schemas.common import (
    AOICreateRequest, AOIResponse, AOIUpdateRequest, AOIStats,
    AdministrativeBoundaryAOICreate, AdministrativeBoundaryChoice, AdministrativeBoundaryPage,
    GeoPackageLayer, GeoPackageLayerList,
)
from app.utils.geo_utils import compute_aoi_stats
from app.utils.validators import validate_aoi_geometry
from app.services.source_data.boundaries import approved_boundary_sources, boundary_features, boundary_lineage, selected_boundary
from app.services.source_data.readiness import SourceNotReady, load_registered_source

router = APIRouter(prefix="/aoi", tags=["AOI"], dependencies=[Depends(verify_internal_secret)])

_MAX_AOI_ARCHIVE_BYTES = 20 * 1024 * 1024


def _uploaded_shapefile_geometry(archive_bytes: bytes) -> dict:
    """Safely read one zipped shapefile and normalize its geometry to WGS84."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = archive.infolist()
            if any(Path(member.filename).is_absolute() or ".." in Path(member.filename).parts for member in members):
                raise ValueError("The ZIP contains an unsafe path.")
            shapefiles = [member for member in members if member.filename.lower().endswith(".shp")]
            if len(shapefiles) != 1:
                raise ValueError("Upload one ZIP containing exactly one .shp file and its sidecar files.")
            with tempfile.TemporaryDirectory(prefix="nova-aoi-") as directory:
                archive.extractall(directory)
                frame = gpd.read_file(Path(directory) / shapefiles[0].filename)
                if frame.empty or frame.crs is None:
                    raise ValueError("The shapefile must contain geometry and a defined CRS.")
                geometry = frame.to_crs(4326).geometry.union_all()
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP archive.") from exc

    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("The shapefile must contain Polygon or MultiPolygon geometry.")
    return geometry.__geo_interface__


def _polygon_geopackage_layers(path: Path):
    layers = gpd.list_layers(path)
    return layers[layers.geometry_type.isin(["Polygon", "MultiPolygon"])]


def _uploaded_geopackage_geometry(file_bytes: bytes, layer_name: str | None = None) -> dict:
    """Read a selected vetted polygon layer; retain legacy single-layer behavior."""
    with tempfile.TemporaryDirectory(prefix="nova-gpkg-aoi-") as directory:
        path = Path(directory) / "aoi.gpkg"
        path.write_bytes(file_bytes)
        try:
            polygon_layers = _polygon_geopackage_layers(path)
        except (OSError, ValueError, DataSourceError) as exc:
            raise ValueError("GeoPackage polygon layers could not be read.") from exc
        names = polygon_layers["name"].astype(str).tolist()
        if layer_name is None:
            if len(names) != 1:
                raise ValueError("Select one GeoPackage Polygon or MultiPolygon layer.")
            selected = names[0]
        elif layer_name not in names:
            raise ValueError("Selected GeoPackage layer is not an available polygon layer.")
        else:
            selected = layer_name
        try:
            frame = gpd.read_file(path, layer=selected)
        except (OSError, ValueError, DataSourceError) as exc:
            raise ValueError("Selected GeoPackage polygon layer could not be read.") from exc
    if frame.empty or frame.crs is None:
        raise ValueError("GeoPackage polygon layer must have geometry and a defined CRS.")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("GeoPackage polygon layer contains null or empty geometry.")
    if not frame.geometry.is_valid.all():
        raise ValueError("GeoPackage polygon layer contains invalid geometry.")
    geometry = frame.to_crs(4326).geometry.union_all()
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("GeoPackage must contain Polygon or MultiPolygon geometry.")
    return geometry.__geo_interface__


@router.post("", response_model=AOIResponse, status_code=status.HTTP_201_CREATED)
def create_aoi(
    payload: AOICreateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AOIResponse:
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)

    if payload.crs.upper() != "EPSG:4326":
        raise HTTPException(
            status_code=422,
            detail="GeoJSON AOI coordinates must use EPSG:4326. Reproject before submission.",
        )

    if payload.source_type.value == "admin_boundary":
        raise HTTPException(status_code=422, detail="Select administrative boundaries from the approved catalogue.")
    return _persist_aoi(payload, db)


def _persist_aoi(payload: AOICreateRequest, db: Session, *, source_lineage: dict | None = None) -> AOIResponse:
    geometry_dict = payload.geometry.model_dump()
    try:
        validate_aoi_geometry(geometry_dict)
        stats = compute_aoi_stats(geometry_dict)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    shapely_geom = shape(geometry_dict)
    # Normalize to MultiPolygon for consistent storage
    if shapely_geom.geom_type == "Polygon":
        from shapely.geometry import MultiPolygon

        shapely_geom = MultiPolygon([shapely_geom])

    aoi = AOI(
        project_id=payload.project_id,
        name=payload.name,
        source_type=payload.source_type.value,
        geometry=from_shape(shapely_geom, srid=4326),
        area_m2=stats["area_m2"],
        area_hectares=stats["area_hectares"],
        area_km2=stats["area_km2"],
        perimeter_m=stats["perimeter_m"],
        source_lineage=source_lineage,
    )
    db.add(aoi)
    db.commit()
    db.refresh(aoi)

    return serialize_aoi(aoi)


@router.get("/admin-boundaries", response_model=AdministrativeBoundaryPage)
def search_administrative_boundaries(
    project_id: uuid.UUID,
    query: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=25, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AdministrativeBoundaryPage:
    require_active_membership(db, context)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    needle = query.strip().casefold()
    if len(needle) < 2:
        raise HTTPException(status_code=422, detail="Search requires at least two non-space characters.")
    matches: list[AdministrativeBoundaryChoice] = []
    total = 0
    for source in approved_boundary_sources(db, project_id):
        for feature in boundary_features(source):
            properties = feature["properties"]
            if not any(needle in str(properties[key]).casefold() for key in ("spatial_unit_id", "name", "level")):
                continue
            if offset <= total < offset + limit:
                matches.append(AdministrativeBoundaryChoice(
                    dataset_id=source.dataset.id,
                    spatial_unit_id=properties["spatial_unit_id"],
                    name=properties["name"],
                    level=properties["level"],
                    source_id=source.manifest.source_id,
                    source_sha256=source.manifest.sha256.lower(),
                    source_version=source.dataset.created_at,
                    producer=source.manifest.provenance.producer,
                    custodian=source.manifest.provenance.custodian,
                    licence_identifier=source.manifest.licence.identifier,
                    permitted_use=source.manifest.licence.permitted_use,
                    redistribution=source.manifest.licence.redistribution,
                    observed_at=properties["observed_at"],
                    positional_uncertainty_m=source.manifest.positional_uncertainty_m,
                    reviewed_at=source.evidence["reviewed_at"],
                    geometry=feature["geometry"],
                ))
            total += 1
    return AdministrativeBoundaryPage(items=matches, total=total, limit=limit, offset=offset)


@router.post("/from-admin-boundary", response_model=AOIResponse, status_code=status.HTTP_201_CREATED)
def create_aoi_from_administrative_boundary(
    payload: AdministrativeBoundaryAOICreate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AOIResponse:
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    record = db.get(Dataset, payload.dataset_id)
    if record is None or record.project_id != project.id:
        raise HTTPException(status_code=404, detail="Approved boundary source not found for this project.")
    try:
        source = load_registered_source(db, record.id, project.id)
        feature = selected_boundary(source, payload.spatial_unit_id)
    except SourceNotReady as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _persist_aoi(
        AOICreateRequest(project_id=project.id, name=payload.name, source_type="admin_boundary", geometry=feature["geometry"]),
        db, source_lineage=boundary_lineage(source, feature),
    )


@router.post("/upload", response_model=AOIResponse, status_code=status.HTTP_201_CREATED)
async def upload_shapefile_aoi(
    project_id: uuid.UUID = Form(...),
    name: str = Form("Uploaded AOI"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AOIResponse:
    """Create an AOI from a ZIP containing one shapefile; archive contents are never retained."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Upload a .zip containing a shapefile.")
    archive_bytes = await file.read(_MAX_AOI_ARCHIVE_BYTES + 1)
    if len(archive_bytes) > _MAX_AOI_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="AOI archive exceeds the 20 MB limit.")
    try:
        geometry = _uploaded_shapefile_geometry(archive_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()

    return create_aoi(
        AOICreateRequest(project_id=project_id, name=name, source_type="shapefile", geometry=geometry),
        db=db,
        context=context,
    )


@router.post("/upload-gpkg", response_model=AOIResponse, status_code=status.HTTP_201_CREATED)
async def upload_geopackage_aoi(
    project_id: uuid.UUID = Form(...),
    name: str = Form("Uploaded AOI"),
    layer_name: str | None = Form(None, max_length=255),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AOIResponse:
    """Normalize the explicitly selected bounded polygon layer; retain no uploaded file."""
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    if not file.filename or not file.filename.lower().endswith(".gpkg"):
        raise HTTPException(status_code=422, detail="Upload a .gpkg polygon layer.")
    file_bytes = await file.read(_MAX_AOI_ARCHIVE_BYTES + 1)
    if len(file_bytes) > _MAX_AOI_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="AOI GeoPackage exceeds the 20 MB limit.")
    try:
        geometry = _uploaded_geopackage_geometry(file_bytes, layer_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
    return create_aoi(
        AOICreateRequest(project_id=project_id, name=name, source_type="gpkg", geometry=geometry),
        db=db,
        context=context,
    )


@router.post("/gpkg-layers", response_model=GeoPackageLayerList)
async def list_geopackage_layers(
    project_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> GeoPackageLayerList:
    """Inspect polygon layer names only; upload bytes are discarded after the request."""
    require_active_membership(db, context)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_project_access(project, context)
    require_engine_entitlement(db, context, project.engine_key)
    if not file.filename or not file.filename.lower().endswith(".gpkg"):
        raise HTTPException(status_code=422, detail="Upload a .gpkg polygon layer.")
    file_bytes = await file.read(_MAX_AOI_ARCHIVE_BYTES + 1)
    await file.close()
    if len(file_bytes) > _MAX_AOI_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="AOI GeoPackage exceeds the 20 MB limit.")
    with tempfile.TemporaryDirectory(prefix="nova-gpkg-layers-") as directory:
        path = Path(directory) / "aoi.gpkg"
        path.write_bytes(file_bytes)
        try:
            polygon_layers = _polygon_geopackage_layers(path)
        except (OSError, ValueError, DataSourceError) as exc:
            raise HTTPException(status_code=422, detail="GeoPackage layers could not be read.") from exc
    if polygon_layers.empty:
        raise HTTPException(status_code=422, detail="GeoPackage has no polygon layers.")
    return GeoPackageLayerList(layers=[
        GeoPackageLayer(name=str(row["name"]), geometry_type=str(row["geometry_type"]))
        for _, row in polygon_layers.iterrows()
    ])


@router.get("/{aoi_id}", response_model=AOIResponse)
def get_aoi(
    aoi_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AOIResponse:
    aoi = db.get(AOI, aoi_id)
    if aoi is None:
        raise HTTPException(status_code=404, detail="AOI not found.")
    require_active_membership(db, context)
    require_project_access(aoi.project, context)
    require_engine_entitlement(db, context, aoi.project.engine_key)
    return serialize_aoi(aoi)


@router.patch("/{aoi_id}", response_model=AOIResponse)
def update_aoi(
    aoi_id: uuid.UUID,
    payload: AOIUpdateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AOIResponse:
    aoi = db.get(AOI, aoi_id)
    if aoi is None:
        raise HTTPException(status_code=404, detail="AOI not found.")
    require_active_membership(db, context)
    require_project_access(aoi.project, context)
    require_engine_entitlement(db, context, aoi.project.engine_key)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.ANALYST)
    aoi.name = payload.name.strip()
    if not aoi.name:
        raise HTTPException(status_code=422, detail="AOI name cannot be empty.")
    db.commit()
    db.refresh(aoi)
    return serialize_aoi(aoi)


@router.delete("/{aoi_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_aoi(
    aoi_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> Response:
    """Delete only an AOI with no task or result history."""
    aoi = db.get(AOI, aoi_id)
    if aoi is None:
        raise HTTPException(status_code=404, detail="AOI not found.")
    require_active_membership(db, context)
    require_project_access(aoi.project, context)
    require_engine_entitlement(db, context, aoi.project.engine_key)
    require_role(context, OrganizationRole.OWNER, OrganizationRole.ADMIN)
    if (
        db.query(Task.id).filter(Task.aoi_id == aoi.id).first()
        or db.query(Result.id).filter(Result.aoi_id == aoi.id).first()
    ):
        raise HTTPException(status_code=409, detail="AOI has job or result history and cannot be deleted.")
    db.delete(aoi)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
