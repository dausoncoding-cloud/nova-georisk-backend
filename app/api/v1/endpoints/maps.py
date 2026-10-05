"""
Flood map product endpoints — Doc 2's 12 standard flood analysis maps.
Each takes already-extracted sample values (not raw rasters — GeoTIFF
generation is a separate, filesystem-bound concern in
app/services/maps/export.py) and returns computed + classified values
with their legend labels/colors, ready for a frontend to render
directly as colored markers, a table, or a legend.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from geoalchemy2.shape import to_shape
from PIL import Image
from sqlalchemy.orm import Session

from app.core.artifact_storage import artifact_root
from app.core.entitlements import require_active_membership, require_current_engine, require_engine_entitlement
from app.core.security import RequestContext, get_request_context, require_project_access, verify_internal_secret
from app.db.session import get_db
from app.models.aoi import AOI
from app.models.project import Project
from app.models.result import Result
from app.schemas.atlas import AtlasManifestResponse
from app.schemas.maps import (
    ClassifiedValuesResponse,
    DurationRequest,
    ExposureDensityRequest,
    FloodDepthRequest,
    FloodExtentRequest,
    FloodExtentResponse,
    FloodHazardMapRequest,
    FloodVelocityRequest,
    ProbabilityRequest,
    ReturnPeriodFromProbabilityRequest,
    RiskMapRequest,
    SusceptibilityRequest,
    VulnerabilityMapRequest,
    ZonationRequest,
)
from app.services.maps import flood_products
from app.services.maps import legends

router = APIRouter(
    prefix="/maps",
    tags=["Flood Maps"],
    dependencies=[Depends(verify_internal_secret), Depends(require_current_engine("firris"))],
)


@router.get("/atlas/{project_id}/{aoi_id}/products/{product_key}")
def get_legacy_atlas_product(
    project_id: uuid.UUID,
    aoi_id: uuid.UUID,
    product_key: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
):
    project = db.get(Project, project_id)
    aoi = db.get(AOI, aoi_id)
    if project is None or aoi is None or aoi.project_id != project_id:
        raise HTTPException(status_code=404, detail="Atlas product not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    if project.engine_key != "firris":
        raise HTTPException(status_code=404, detail="Atlas product not found.")
    require_engine_entitlement(db, context, "firris")
    output_dir = artifact_root() / str(project_id) / str(aoi_id)
    metadata_path = output_dir / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(status_code=404, detail="Atlas product not found.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Screening atlas metadata is invalid.") from exc
    product = next((item for item in metadata.get("products", []) if item.get("key") == product_key), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Atlas product not found.")
    filename = Path(product.get("url", "")).name
    product_path = (output_dir / filename).resolve()
    if product_path.parent != output_dir.resolve() or not product_path.is_file():
        raise HTTPException(status_code=404, detail="Atlas product not found.")
    return FileResponse(product_path, media_type="image/png")


@router.get("/atlas/{project_id}/{aoi_id}", response_model=AtlasManifestResponse)
def get_flood_screening_atlas(
    project_id: uuid.UUID,
    aoi_id: uuid.UUID,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context),
) -> AtlasManifestResponse:
    """
    Generic screening-atlas manifest for any project/AOI — reads
    whatever `generate_flood_screening_atlas()` (triggered via
    `POST /ingestion/screening-atlas`) wrote to
    `{OUTPUT_STORAGE_DIR}/{project_id}/{aoi_id}/metadata.json`.
    Works for any AOI, not one specific location.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_active_membership(db, context)
    require_project_access(project, context)
    if project.engine_key != "firris":
        raise HTTPException(status_code=404, detail="Project not found.")
    require_engine_entitlement(db, context, "firris")
    aoi = db.get(AOI, aoi_id)
    if aoi is None or aoi.project_id != project_id:
        raise HTTPException(status_code=404, detail="AOI not found for this project.")

    persisted = (
        db.query(Result)
        .filter(
            Result.project_id == project_id,
            Result.aoi_id == aoi_id,
            Result.engine_key == "firris",
            Result.result_type == "screening_atlas",
        )
        .order_by(Result.version.desc())
        .first()
    )
    if persisted is not None and persisted.summary and persisted.summary.get("products"):
        return AtlasManifestResponse.model_validate(persisted.summary)

    # Backward-compatible read path for atlas files produced before versioned
    # Result persistence.  Their renderer did not declare an output CRS, so
    # crs remains null and the frontend must treat them as gallery previews.
    output_dir = artifact_root() / str(project_id) / str(aoi_id)
    metadata_path = output_dir / "metadata.json"

    if not metadata_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No screening atlas found for project={project_id} aoi={aoi_id}. "
                "Trigger one via POST /ingestion/screening-atlas first."
            ),
        )

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Screening atlas metadata is invalid.") from exc

    min_x, min_y, max_x, max_y = to_shape(aoi.geometry).bounds
    bounds = [float(min_x), float(min_y), float(max_x), float(max_y)]
    for product in metadata.get("products", []):
        filename = Path(product["url"]).name
        product_path = output_dir / filename
        if not product_path.is_file():
            raise HTTPException(status_code=404, detail=f"Atlas output file is missing: {filename}")
        with Image.open(product_path) as rendered:
            width, height = rendered.size
        product.update(
            {
                "url": f"/api/v1/maps/atlas/{project_id}/{aoi_id}/products/{product['key']}",
                "filename": filename,
                "bounds": bounds,
                "crs": None,
                "width": width,
                "height": height,
                "units": None,
                "nodata": None,
                "legend": None,
            }
        )

    metadata.update(
        {
            "result_id": None,
            "version": 0,
            "bounds": bounds,
            "crs": None,
            "provenance": {
                "renderer": "Legacy Google Earth Engine thumbnail",
                "limitations": [
                    "Output CRS was not declared when this legacy PNG was rendered.",
                    "Display as a preview only; do not georeference it on a web map.",
                ],
            },
            "legacy": True,
        }
    )

    return AtlasManifestResponse.model_validate(metadata)


def _classify_scalar_each(values: list[float], classify_fn) -> ClassifiedValuesResponse:
    """For classify_* functions that take one float and return a Band."""
    bands = [classify_fn(v) for v in values]
    return ClassifiedValuesResponse(
        values=values,
        labels=[b.label for b in bands],
        colors=[b.color_hex for b in bands],
    )


@router.post("/extent", response_model=FloodExtentResponse)
def flood_extent(payload: FloodExtentRequest) -> FloodExtentResponse:
    """SAR backscatter-ratio flood detection — Doc 2 Map 1."""
    mask = flood_products.compute_flood_extent(
        np.array(payload.backscatter_before),
        np.array(payload.backscatter_during),
        change_ratio_threshold=payload.change_ratio_threshold,
    )
    return FloodExtentResponse(flooded=mask.tolist())


@router.post("/depth", response_model=ClassifiedValuesResponse)
def flood_depth(payload: FloodDepthRequest) -> ClassifiedValuesResponse:
    """Depth = WSE - Ground — Doc 2 Map 2."""
    depth = flood_products.compute_flood_depth(
        np.array(payload.water_surface_elevation), np.array(payload.ground_elevation)
    )
    return _classify_scalar_each(depth.tolist(), flood_products.classify_depth)


@router.post("/velocity", response_model=ClassifiedValuesResponse)
def flood_velocity(payload: FloodVelocityRequest) -> ClassifiedValuesResponse:
    """Velocity = Discharge / Area — Doc 2 Map 3."""
    velocity = flood_products.compute_flood_velocity(
        np.array(payload.discharge), np.array(payload.cross_sectional_area)
    )
    return _classify_scalar_each(velocity.tolist(), flood_products.classify_velocity)


@router.post("/hazard", response_model=ClassifiedValuesResponse)
def flood_hazard_map(payload: FloodHazardMapRequest) -> ClassifiedValuesResponse:
    """
    Hazard Index = Depth x Velocity, quantile-classified — Doc 2 Map 4.
    Distinct from /firas/hazard: this is the raw depth*velocity product
    map, not the entropy-weighted FIRRIS Hazard Index (H).
    """
    depth = np.array(payload.depth)
    velocity = np.array(payload.velocity)
    hazard_index = flood_products.compute_hazard_index(depth, velocity)
    labels = flood_products.classify_hazard_index(hazard_index)
    colors = [legends.color_for_label(label, legends.HAZARD_MAP_BANDS) for label in labels]
    return ClassifiedValuesResponse(values=hazard_index.tolist(), labels=labels.tolist(), colors=colors)


@router.post("/probability", response_model=ClassifiedValuesResponse)
def flood_probability(payload: ProbabilityRequest) -> ClassifiedValuesResponse:
    """Inundation probability classification — Doc 2 Map 5."""
    try:
        return _classify_scalar_each(payload.probability, flood_products.classify_probability)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/return-period", response_model=ClassifiedValuesResponse)
def flood_return_period(payload: ReturnPeriodFromProbabilityRequest) -> ClassifiedValuesResponse:
    """Return Period = 1 / Annual Probability, classified by frequency — Doc 2 Map 7."""
    try:
        return_periods = [flood_products.probability_to_return_period(p) for p in payload.annual_probability]
        return _classify_scalar_each(return_periods, flood_products.classify_return_period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/duration", response_model=ClassifiedValuesResponse)
def flood_duration(payload: DurationRequest) -> ClassifiedValuesResponse:
    """Flood duration classification — Doc 2 Map 6."""
    return _classify_scalar_each(payload.duration_days, flood_products.classify_duration)


@router.post("/exposure", response_model=ClassifiedValuesResponse)
def flood_exposure_density(payload: ExposureDensityRequest) -> ClassifiedValuesResponse:
    """Population/asset density classification — Doc 2 Map 8."""
    try:
        return _classify_scalar_each(payload.normalized_density, flood_products.classify_exposure_density)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/vulnerability", response_model=ClassifiedValuesResponse)
def flood_vulnerability_map(payload: VulnerabilityMapRequest) -> ClassifiedValuesResponse:
    """FVI classification for map display — Doc 2 Map 9."""
    try:
        return _classify_scalar_each(payload.fvi, flood_products.classify_vulnerability_map)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/risk", response_model=ClassifiedValuesResponse)
def flood_risk_map(payload: RiskMapRequest) -> ClassifiedValuesResponse:
    """Risk = Hazard x Exposure x Vulnerability, 6-tier classification — Doc 2 Map 10."""
    try:
        risk = flood_products.compute_flood_risk(
            np.array(payload.hazard), np.array(payload.exposure), np.array(payload.vulnerability)
        )
        return _classify_scalar_each(risk.tolist(), flood_products.classify_risk_map)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/susceptibility", response_model=ClassifiedValuesResponse)
def flood_susceptibility_map(payload: SusceptibilityRequest) -> ClassifiedValuesResponse:
    """Susceptibility classification — Doc 2 Map 11."""
    try:
        return _classify_scalar_each(payload.susceptibility, flood_products.classify_susceptibility)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/zonation", response_model=ClassifiedValuesResponse)
def flood_zonation_map(payload: ZonationRequest) -> ClassifiedValuesResponse:
    """Hazard zonation, 6-tier classification — Doc 2 Map 12."""
    try:
        return _classify_scalar_each(payload.zonation_score, flood_products.classify_zonation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
