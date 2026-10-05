"""Protected completion archive; scientific source artifacts remain unchanged."""
import json
import zipfile

from app.platform.result_exports import artifact_entry, artifact_fingerprint
from app.services.tasks.execution import execution_record, redact_snapshot


def completion_archive(directory, task, result, output_files):
    path = directory / "execution-archive.json"
    content = {"schema_version": "1.0", "task_id": str(task.id), "result_id": str(result.id),
               "project_id": str(task.project_id), "aoi_id": str(task.aoi_id),
               "engine_key": task.engine_key, "result_type": result.result_type, "result_version": result.version,
               "submitted_parameters": redact_snapshot(task.input_params or {}),
               "execution": execution_record(task),
               "scientific_provenance": result.provenance,
               "artifacts": {key: {field: value for field, value in entry.items() if field != "path"} for key, entry in output_files.items()},
               "limitations": ["The execution archive retains submitted parameters and observed lifecycle events; external scientific validation is not asserted.",
                               "Secret-like parameter fields are redacted in this export; the full persisted-input fingerprint remains recorded."]}
    path.write_text(json.dumps(content, indent=2, default=str, allow_nan=False), encoding="utf-8")
    entry = artifact_entry(path, label="Execution archive", media_type="application/json", artifact_type="report",
        result_version=result.version, role="export")
    package = output_files.get("report_package")
    if package:
        package_path = directory / package["path"]
        with zipfile.ZipFile(package_path, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.write(path, "execution-archive.json")
        size, digest = artifact_fingerprint(package_path)
        package.update(file_size_bytes=size, checksum_sha256=digest)
    return entry
