"""Response serializers for ORM objects with geospatial/related fields."""
from __future__ import annotations

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from app.api.v1.result_overview import build_result_overview
from app.models.aoi import AOI
from app.models.result import Result
from app.models.task import Task
from app.schemas.common import AOIResponse, AOIStats, ResultReference, TaskStatusResponse
from app.schemas.results import ResultLayerResponse, ResultProductResponse, ResultResponse


def serialize_aoi(aoi: AOI) -> AOIResponse:
    return AOIResponse(
        id=aoi.id,
        project_id=aoi.project_id,
        name=aoi.name,
        source_type=aoi.source_type,
        geometry=mapping(to_shape(aoi.geometry)),
        crs="EPSG:4326",
        stats=AOIStats(
            area_m2=aoi.area_m2,
            area_hectares=aoi.area_hectares,
            area_km2=aoi.area_km2,
            perimeter_m=aoi.perimeter_m,
        ),
        created_at=aoi.created_at,
        source_lineage=aoi.source_lineage,
    )


def serialize_task(task: Task, result: Result | None = None) -> TaskStatusResponse:
    result_reference = None
    if result is not None:
        result_reference = ResultReference(
            id=result.id,
            result_type=result.result_type,
            version=result.version,
            created_at=result.created_at,
        )
    safe_error = task.error_summary
    payload = task.result_payload
    execution = (payload or {}).get("execution_record")
    if execution is not None:
        from app.services.tasks.execution import verify_events
        try:
            verify_events(execution)
        except (ValueError, TypeError, KeyError):
            execution = None
            payload = {**payload, "execution_record": None, "execution_integrity_error": True}
    return TaskStatusResponse(
        id=task.id,
        task_id=task.id,
        project_id=task.project_id,
        engine_key=task.engine_key,
        aoi_id=task.aoi_id,
        task_type=task.task_type.value,
        status=task.status.value,
        progress_pct=task.progress_pct,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error_summary=safe_error,
        error_message=safe_error,
        result_payload=payload,
        result_reference=result_reference,
        execution=execution,
    )


LEGACY_FIRRIS_NOTICE = (
    "Produced before the JRC never-water correction; analysis was restricted to historically wet pixels. "
    "Metrics are internal agreement with SAR screening labels. Downloaded files from this run use older labels "
    "(\u201cFlood Probability\u201d, \u201cFlood Risk Index Summary\u201d); the score is a model confidence score, "
    "not a probability of flooding."
)
FIRRIS_SCIENCE_VERSION = "firris-science-2"


def legacy_interpretation_notice(result: Result) -> str | None:
    """Notice for FIRRIS GEE results produced before firris-science-2 (Bundle 1). Stored data is untouched."""
    provenance = result.provenance if isinstance(result.provenance, dict) else {}
    if result.engine_key != "firris" or "per_scene_lineage" not in provenance:
        return None
    return None if provenance.get("science_version") == FIRRIS_SCIENCE_VERSION else LEGACY_FIRRIS_NOTICE


CLIENT_DELIVERABLE_KEYS = {"scientific_report_pdf", "scientific_report_word", "firris_excel_report", "report_package"}
# Model point sets (training/test samples, independent reference audit sample, hold-out points) in every format.
AUDIT_KEY_PREFIXES = ("samples", "independent_reference_points", "validation_holdout_points")
GIS_DELIVERY_TYPES = {"gis_layer_zip", "gpkg", "kml", "shapefile_zip"}


def deliverable_group(key: str, entry: dict) -> str:
    """Plan item 2.5: which download group an artifact belongs to (also for legacy results)."""
    delivery = entry.get("delivery_type")
    if key.startswith(AUDIT_KEY_PREFIXES):
        return "audit"  # model point sets are evidence for checking the model, not map data
    if key in CLIENT_DELIVERABLE_KEYS or delivery in {"map_png", "map_pdf"}:
        return "client_deliverable"
    if (entry.get("role", "product") == "product" and entry.get("artifact_type") in {"raster", "vector"}) or delivery in GIS_DELIVERY_TYPES:
        return "gis_data"
    if key.startswith(("figure_", "accuracy_")):
        return "figures"
    return "audit"


def serialize_result(result: Result) -> ResultResponse:
    """Serialize result metadata without leaking server filesystem paths."""
    products = []
    exports = []
    layer_groups: dict[tuple[str, str], dict] = {}
    for key, entry in sorted((result.output_files or {}).items()):
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        role = entry.get("role", "product")
        media_type = entry.get("media_type", "application/octet-stream")
        artifact_type = entry.get("artifact_type")
        if artifact_type is None:
            artifact_type = "preview" if media_type.startswith("image/") else "metadata"
        artifact = ResultProductResponse(
            key=key,
            label=entry.get("label", key.replace("_", " ").title()),
            url=f"/api/v1/results/{result.id}/products/{key}",
            media_type=media_type,
            delivery_type=entry.get("delivery_type", "file"),
            format=entry.get("format", "unknown"),
            gis_metadata=entry.get("gis_metadata"),
            artifact_type=artifact_type,
            role=role,
            product_key=entry.get("product_key"),
            schema_version=entry.get("schema_version", "1.0"),
            result_version=entry.get("result_version", result.version),
            file_size_bytes=entry.get("file_size_bytes"),
            checksum_sha256=entry.get("checksum_sha256"),
            deliverable_group=deliverable_group(key, entry),
        )
        if role == "export":
            exports.append(artifact)
        else:
            products.append(artifact)
        layer = entry.get("layer")
        if role == "product" and isinstance(layer, dict):
            product_key = entry.get("product_key", key)
            layer_type = layer.get("layer_type", "raster")
            group_key = (product_key, layer_type)
            existing = layer_groups.get(group_key)
            available = set(layer.get("available_delivery_types") or [])
            planned = set(layer.get("planned_delivery_types") or [])
            if existing is None:
                from app.services.reporting.evidence import display_bounds
                geographic_bounds = None
                if layer.get("renderable") and layer.get("crs") and layer.get("bounding_box"):
                    geographic_bounds = display_bounds(layer["crs"], layer["bounding_box"])
                meta = entry.get("gis_metadata") or {}
                layer_groups[group_key] = {
                    "key": f"{product_key}_{layer_type}",
                    "label": artifact.label,
                    "product_key": product_key,
                    "layer_type": layer_type,
                    "crs": layer.get("crs"),
                    "bounding_box": layer.get("bounding_box"),
                    "spatial_resolution": layer.get("spatial_resolution"),
                    "units": layer.get("units"),
                    "nodata": layer.get("nodata"),
                    "legend": layer.get("legend"),
                    "renderable": bool(layer.get("renderable", False)),
                    "rendering_reason": layer.get("rendering_reason"),
                    "available_delivery_types": available,
                    "planned_delivery_types": planned,
                    "artifact_keys": [key],
                    "display_bounds_wgs84": geographic_bounds,
                    "temporal_metadata": {name: meta[name] for name in ("target_period", "baseline_period", "before_timestamp", "after_timestamp", "observation_definition", "timestamps", "temporal_resolution_hours") if meta.get(name) is not None} or None,
                }
            else:
                existing["renderable"] = existing["renderable"] or bool(layer.get("renderable", False))
                if existing["renderable"]:
                    existing["rendering_reason"] = None
                existing["available_delivery_types"].update(available)
                existing["planned_delivery_types"].update(planned)
                existing["artifact_keys"].append(key)
    layers = [
        ResultLayerResponse(
            **{
                **item,
                "available_delivery_types": sorted(item["available_delivery_types"]),
                "planned_delivery_types": sorted(item["planned_delivery_types"]),
            }
        )
        for item in layer_groups.values()
    ]
    return ResultResponse(
        id=result.id,
        task_id=result.task_id,
        project_id=result.project_id,
        aoi_id=result.aoi_id,
        engine_key=result.engine_key,
        result_type=result.result_type,
        version=result.version,
        summary=result.summary,
        analytics=(result.summary or {}).get("delivery"),
        interpretation=(result.summary or {}).get("interpretation"),
        validation_dashboard=(result.summary or {}).get("validation_dashboard"),
        interpretation_notice=legacy_interpretation_notice(result),
        overview=build_result_overview(result),
        decision_support=(result.summary or {}).get("decision_support"),
        provenance=result.provenance,
        products=products,
        layers=layers,
        exports=exports,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )
