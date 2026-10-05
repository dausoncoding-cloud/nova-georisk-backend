"""Engine-neutral metadata reports and downloadable result packages."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


ARTIFACT_SCHEMA_VERSION = "1.0"


def artifact_fingerprint(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def artifact_entry(
    path: Path,
    *,
    label: str,
    media_type: str,
    artifact_type: str,
    result_version: int,
    role: str,
    product_key: str | None = None,
    delivery_type: str | None = None,
    format_name: str | None = None,
    gis_metadata: dict[str, Any] | None = None,
    layer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    size, checksum = artifact_fingerprint(path)
    return {
        "path": path.name,
        "download_name": path.name,
        "label": label,
        "media_type": media_type,
        "artifact_type": artifact_type,
        "role": role,
        "product_key": product_key,
        "delivery_type": delivery_type or artifact_type,
        "format": format_name or path.suffix.lstrip(".").lower(),
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "result_version": result_version,
        "file_size_bytes": size,
        "checksum_sha256": checksum,
        "gis_metadata": gis_metadata,
        "layer": layer,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_result_exports(
    output_directory: Path,
    *,
    task_id: str,
    project_id: str,
    aoi_id: str,
    engine_key: str,
    engine_version: str,
    result_type: str,
    result_version: int,
    summary: dict[str, Any],
    provenance: dict[str, Any],
    gis_metadata: dict[str, Any],
    product_entries: dict[str, dict[str, Any]],
    supplemental_entries: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Create truthful JSON reports and one ZIP containing delivered artifacts."""
    common = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "task_id": task_id,
        "project_id": project_id,
        "aoi_id": aoi_id,
        "engine_key": engine_key,
        "engine_version": engine_version,
        "result_type": result_type,
        "result_version": result_version,
    }
    summary_path = output_directory / "analysis-summary.json"
    metadata_path = output_directory / "result-metadata.json"
    provenance_path = output_directory / "provenance.json"
    package_path = output_directory / "firris-result-package.zip"

    # Import here to keep the artifact-entry helper available to the renderer.
    from app.services.maps.cartography import build_cartographic_exports

    map_entries = (
        build_cartographic_exports(
            output_directory,
            product_entries=product_entries,
            provenance=provenance,
            result_version=result_version,
        )
        if engine_key == "firris" else {}
    )

    delivery_entries = {}
    if engine_key == "firris":
        from app.services.reporting.evidence import quantitative_delivery, interpret_evidence
        from app.services.reporting.complete_report import complete_report
        from app.services.maps.vector_formats import export_vector_formats
        analytics = quantitative_delivery(output_directory, product_entries, summary, provenance)
        interpretation = interpret_evidence(analytics, summary, provenance)
        summary["delivery"] = analytics
        summary["interpretation"] = interpretation
        for name, value in (("quantitative_data", analytics), ("evidence_interpretation", interpretation)):
            path = output_directory / (name + ".json")
            _write_json(path, value)
            delivery_entries[name] = artifact_entry(path, label=name.replace("_", " ").title(),
                media_type="application/json", artifact_type="report", result_version=result_version, role="export")
        for name, (path, media) in complete_report(output_directory, common, gis_metadata, summary,
                provenance, analytics, interpretation).items():
            delivery_entries[name] = artifact_entry(path, label=name.replace("_", " ").title(),
                media_type=media, artifact_type="report", result_version=result_version, role="export")
        for name, entry in {**product_entries, **(supplemental_entries or {})}.items():
            if entry.get("artifact_type") == "vector" and entry.get("format") == "geojson":
                for format_name, (path, metadata) in export_vector_formats(output_directory, name, entry, provenance).items():
                    delivery_entries[name + "_" + format_name] = artifact_entry(path,
                        label=entry.get("label", name) + " " + format_name,
                        media_type={"gpkg": "application/geopackage+sqlite3", "kml": "application/vnd.google-earth.kml+xml", "shapefile_zip": "application/zip"}[format_name],
                        artifact_type="vector", result_version=result_version, role="export",
                        product_key=entry.get("product_key"), delivery_type=format_name, format_name=format_name,
                        gis_metadata=metadata)

    _write_json(summary_path, {**common, "summary": summary})
    _write_json(
        metadata_path,
        {
            **common,
            "gis_metadata": gis_metadata,
            "artifacts": [
                {key: value for key, value in entry.items() if key != "path"}
                for entry in [*product_entries.values(), *map_entries.values(), *delivery_entries.values(), *(supplemental_entries or {}).values()]
            ],
        },
    )
    _write_json(provenance_path, {**common, "provenance": provenance})

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [summary_path, metadata_path, provenance_path]:
            archive.write(path, arcname=path.name)
        for entry in [*product_entries.values(), *map_entries.values(), *delivery_entries.values(), *(supplemental_entries or {}).values()]:
            product_path = output_directory / str(entry["path"])
            folder = "products" if entry.get("role") == "product" else "reports"
            archive.write(product_path, arcname=f"{folder}/{product_path.name}")

    return {
        **map_entries,
        **delivery_entries,
        "analysis_summary": artifact_entry(
            summary_path,
            label="Analysis summary",
            media_type="application/json",
            artifact_type="report",
            result_version=result_version,
            role="export",
        ),
        "result_metadata": artifact_entry(
            metadata_path,
            label="Result metadata report",
            media_type="application/json",
            artifact_type="report",
            result_version=result_version,
            role="export",
        ),
        "provenance": artifact_entry(
            provenance_path,
            label="Provenance report",
            media_type="application/json",
            artifact_type="report",
            result_version=result_version,
            role="export",
        ),
        "report_package": artifact_entry(
            package_path,
            label="FIRRIS result package",
            media_type="application/zip",
            artifact_type="package",
            result_version=result_version,
            role="export",
        ),
    }
