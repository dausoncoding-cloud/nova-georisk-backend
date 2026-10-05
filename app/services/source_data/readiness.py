"""Revalidate registered bytes and independent readiness evidence at every science use."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.artifact_storage import artifact_root
from app.models.dataset import Dataset
from app.schemas.source_data import SourceDatasetManifest
from app.services.source_data.catalogue import get_profile
from app.services.source_data.validators import MAX_BYTES, SourceDataValidationError, validate_source_data


class SourceNotReady(ValueError):
    """A registered source is not authorized or scientifically ready for binding."""


@dataclass(frozen=True)
class ReadySource:
    dataset: Dataset
    manifest: SourceDatasetManifest
    data: bytes
    evidence: dict

    def lineage(self) -> dict:
        return {
            "dataset_id": str(self.dataset.id),
            "source_id": self.manifest.source_id,
            "source_version": self.dataset.created_at.isoformat() if self.dataset.created_at else None,
            "category": self.manifest.category,
            "sha256": self.manifest.sha256.lower(),
            "units": self.manifest.units,
            "crs": self.manifest.crs,
            "vertical_datum": self.manifest.vertical_datum,
            "temporal_coverage": self.manifest.temporal_coverage.model_dump(mode="json"),
            "spatial_resolution": self.manifest.spatial_resolution.model_dump() if self.manifest.spatial_resolution else None,
            "licence": self.manifest.licence.model_dump(),
            "provenance": self.manifest.provenance.model_dump(),
            "uncertainty": self.manifest.uncertainty.model_dump(),
            "hydraulic_model_run_id": self.manifest.hydraulic_model_run_id,
            "hydraulic_model_validation_reference": self.manifest.hydraulic_model_validation_reference,
            "observation_year": self.manifest.observation_year,
            "event_definition": self.manifest.event_definition,
            "readiness_evidence": self.evidence,
        }


def load_registered_source(db: Session, dataset_id: uuid.UUID, project_id: uuid.UUID, *, root: Path | None = None,
                           require_ready: bool = True) -> ReadySource:
    record = db.get(Dataset, dataset_id)
    if record is None or record.project_id != project_id:
        raise SourceNotReady("Source dataset is not available in this project")
    metadata = record.metadata_json or {}
    try:
        manifest = SourceDatasetManifest.model_validate(metadata["source_manifest"])
        report = metadata["validation"]
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise SourceNotReady("Source registration metadata is invalid") from exc
    if manifest.project_id != project_id or manifest.category != record.product_type or manifest.source_id != record.source_collection:
        raise SourceNotReady("Source registration metadata does not match database identity")
    evidence = metadata.get("readiness") or {}
    if require_ready:
        if evidence.get("analysis_ready") is not True or evidence.get("sha256", "").lower() != manifest.sha256.lower():
            raise SourceNotReady("Source is not approved for scientific analysis")
        if not evidence.get("evidence_refs") or not evidence.get("reviewed_by") or not evidence.get("checks_complete"):
            raise SourceNotReady("Source readiness evidence is incomplete")
        required_checks = {"qa_verified", "licence_verified", "provenance_verified", "crs_datum_verified", "temporal_coverage_verified", "uncertainty_reviewed"}
        if any(evidence.get("checks", {}).get(key) is not True for key in required_checks):
            raise SourceNotReady("Source readiness checks are incomplete")
    storage_root = (root or artifact_root()).resolve()
    try:
        path = Path(record.processed_asset_ref or "").resolve(strict=True)
        path.relative_to(storage_root)
    except (OSError, ValueError) as exc:
        raise SourceNotReady("Source bytes are unavailable in protected storage") from exc
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise SourceNotReady("Source bytes are unavailable or exceed the size limit")
    data = path.read_bytes()
    try:
        actual = validate_source_data(manifest, data, "source" + {"csv": ".csv", "geojson": ".geojson", "geotiff": ".tif"}[get_profile(manifest.category)["format"]])
    except SourceDataValidationError as exc:
        raise SourceNotReady("Source bytes fail current structural validation") from exc
    if report.get("sha256", "").lower() != actual.sha256 or report.get("analysis_ready") is not False:
        raise SourceNotReady("Source registration attestation is inconsistent")
    return ReadySource(record, manifest, data, evidence)
