"""Response serializers for ORM objects with geospatial/related fields."""
from __future__ import annotations

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

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
        result_payload=task.result_payload,
        result_reference=result_reference,
    )


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
        provenance=result.provenance,
        products=products,
        layers=layers,
        exports=exports,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )
