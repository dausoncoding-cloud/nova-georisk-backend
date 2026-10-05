"""Approved, project-scoped administrative-boundary AOI catalogue."""
from __future__ import annotations

import json
import uuid

from geoalchemy2.shape import to_shape
from shapely.geometry import shape
from sqlalchemy.orm import Session

from app.models.aoi import AOI
from app.models.dataset import Dataset
from app.services.source_data.readiness import ReadySource, SourceNotReady, load_registered_source


def approved_boundary_sources(db: Session, project_id: uuid.UUID):
    """Skip unapproved sources; never surface another project's catalogue."""
    records = db.query(Dataset).filter(
        Dataset.project_id == project_id,
        Dataset.product_type == "administrative_boundaries",
    ).order_by(Dataset.created_at.desc(), Dataset.id.desc())
    for record in records:
        try:
            yield load_registered_source(db, record.id, project_id)
        except SourceNotReady:
            continue


def boundary_features(source: ReadySource):
    if source.manifest.category != "administrative_boundaries":
        raise SourceNotReady("Selected source is not an administrative-boundary catalogue")
    return json.loads(source.data)["features"]


def selected_boundary(source: ReadySource, spatial_unit_id: str):
    matches = [feature for feature in boundary_features(source)
               if feature["properties"]["spatial_unit_id"] == spatial_unit_id]
    if len(matches) != 1:
        raise SourceNotReady("Exactly one approved administrative boundary must match the selected spatial unit")
    return matches[0]


def boundary_lineage(source: ReadySource, feature: dict) -> dict:
    properties = feature["properties"]
    return {
        "dataset_id": str(source.dataset.id),
        "source_id": source.manifest.source_id,
        "source_version": source.dataset.created_at.isoformat(),
        "sha256": source.manifest.sha256.lower(),
        "spatial_unit_id": properties["spatial_unit_id"],
        "boundary_name": properties["name"],
        "boundary_level": properties["level"],
        "observed_at": properties["observed_at"],
        "licence": source.manifest.licence.model_dump(),
        "provenance": source.manifest.provenance.model_dump(),
        "uncertainty": source.manifest.uncertainty.model_dump(),
        "readiness_reviewed_at": source.evidence["reviewed_at"],
    }


def revalidate_boundary_aoi(db: Session, aoi: AOI) -> None:
    """Fail closed if approval, bytes, identity, or selected geometry changed."""
    if aoi.source_type != "admin_boundary":
        return
    lineage = aoi.source_lineage or {}
    try:
        source = load_registered_source(db, uuid.UUID(lineage["dataset_id"]), aoi.project_id)
        feature = selected_boundary(source, lineage["spatial_unit_id"])
    except (KeyError, ValueError) as exc:
        raise SourceNotReady("Administrative-boundary AOI lineage is invalid") from exc
    if (lineage.get("sha256") != source.manifest.sha256.lower()
            or lineage.get("source_version") != source.dataset.created_at.isoformat()
            or not to_shape(aoi.geometry).equals(shape(feature["geometry"]))):
        raise SourceNotReady("Administrative-boundary AOI source or geometry changed after selection")
