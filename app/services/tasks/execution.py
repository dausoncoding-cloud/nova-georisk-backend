"""Durable execution fingerprints/events, bounded admission and queue claims.

Events are access-controlled records with a consistency hash chain, not a claim
of cryptographic protection against administrators who can rewrite the database.
Registered inputs are cached as protected bytes, checked again on each execution;
GEE/result reuse is disabled without immutable remote identity and current QA.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import text

from app.core.config import get_settings
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.schemas.execution import ExecutionRecord

CACHE_POLICY = "revalidate_registered_sources_no_automatic_result_or_gee_reuse"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def implementation_fingerprint():
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for file in sorted(root.rglob("*.py")):
        digest.update(str(file.relative_to(root)).encode())
        digest.update(file.read_bytes())
    digest.update((root.parent / "requirements.txt").read_bytes())
    return digest.hexdigest()


def aoi_fingerprint(aoi):
    return hashlib.sha256(to_shape(aoi.geometry).normalize().wkb).hexdigest() if aoi is not None else None


def execution_record(task):
    return deepcopy((task.result_payload or {}).get("execution_record"))


def initialize_execution(task, aoi=None, *, context=None, retry_of=None):
    task.result_payload = {**(task.result_payload or {}), "execution_record": {
        "schema_version": "1.0", "origin": "api" if context is not None else "legacy_worker",
        "parameters_sha256": fingerprint(task.input_params or {}), "aoi_sha256": aoi_fingerprint(aoi),
        "aoi_snapshot": mapping(to_shape(aoi.geometry)) if aoi else None,
        "aoi_source_lineage": deepcopy(aoi.source_lineage) if aoi else None,
        "implementation_sha256": implementation_fingerprint(), "cache_policy": CACHE_POLICY,
        "retry_of": str(retry_of) if retry_of else None, "events": []}}
    append_event(task, "submitted" if context is not None else "initialized", actor_id=getattr(context, "user_id", None))


def verify_events(record):
    ExecutionRecord.model_validate(record)
    previous = "0" * 64
    for sequence, event in enumerate(record["events"], 1):
        payload = {key: value for key, value in event.items() if key != "sha256"}
        if event["sequence"] != sequence or event["previous_sha256"] != previous or fingerprint(payload) != event["sha256"]:
            raise ValueError("Execution event consistency chain differs")
        previous = event["sha256"]


def append_event(task, action, *, actor_id=None):
    record = execution_record(task)
    if record is None:
        # Legacy status-only jobs retain their old payload until a worker starts.
        return
    verify_events(record)
    event = {"sequence": len(record["events"]) + 1, "action": action,
             "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "actor_id": str(actor_id) if actor_id else None,
             "progress_pct": task.progress_pct or 0,
             "previous_sha256": record["events"][-1]["sha256"] if record["events"] else "0" * 64}
    event["sha256"] = fingerprint(event)
    record["events"].append(event)
    task.result_payload = {**(task.result_payload or {}), "execution_record": record}


def validate_execution(task, aoi):
    record = execution_record(task)
    if record is None:
        initialize_execution(task, aoi)
        record = execution_record(task)
    verify_events(record)
    if (record["parameters_sha256"] != fingerprint(task.input_params or {})
            or record["aoi_sha256"] != aoi_fingerprint(aoi)
            or record["implementation_sha256"] != implementation_fingerprint()):
        raise ValueError("Submitted input, AOI or implementation fingerprint changed; cancel and explicitly resubmit")


def validate_workload(params):
    settings = get_settings()
    encoded = json.dumps(params, allow_nan=False, default=str).encode()
    if len(encoded) > settings.firris_max_request_bytes:
        raise ValueError("FIRRIS request exceeds the bounded persisted-input capacity")
    workflow = (params.get("parameters") or {}).get("workflow") or {}
    labels = workflow.get("label_layer")
    if labels and (len(labels) * len(labels[0]) > settings.firris_max_prepared_cells
                   or len(workflow.get("feature_layers") or {}) > settings.firris_max_feature_layers):
        raise ValueError("Prepared workflow exceeds configured grid/feature capacity")


def admit_task(db, project):
    """Serialize organization admission in PostgreSQL; no broker-only count race."""
    key = int.from_bytes(hashlib.sha256((str(project.organization_id) + ":firris:admission").encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    pending = db.query(Task).join(Project).filter(Project.organization_id == project.organization_id,
        Task.engine_key == "firris", Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING])).count()
    if pending >= get_settings().firris_max_pending_tasks_per_organization:
        raise HTTPException(status_code=429, detail="FIRRIS pending-task capacity is reached. Retry after an existing task finishes.", headers={"Retry-After": "30"})


def claim_task(db, task_id):
    task = db.query(Task).filter(Task.id == task_id).populate_existing().with_for_update().first()
    if task is None or task.status != TaskStatus.QUEUED:
        db.rollback()
        return None
    return task


def redact_snapshot(value):
    if isinstance(value, dict):
        return {key: ("[redacted]" if any(token in key.lower() for token in ("secret", "password", "token", "credential", "private_key")) else redact_snapshot(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_snapshot(item) for item in value]
    return value


def validate_source_snapshots(resolved, params):
    """Recheck the same approved source/Result identities before publication."""
    from app.services.source_data.change import comparison_source_fingerprint
    snapshots = params.get("source_snapshot") or {}
    if set(snapshots) != set(resolved.sources):
        raise ValueError("Source snapshot roles changed after submission")
    for role, source in resolved.sources.items():
        pinned = snapshots[role]
        if (pinned.get("dataset_id") != str(source.dataset.id)
                or pinned.get("sha256") != source.manifest.sha256.lower()
                or pinned.get("reviewed_at") != source.evidence.get("reviewed_at")):
            raise ValueError("Source approval or version changed after submission")
        current = comparison_source_fingerprint(source)
        if pinned.get("manifest_sha256") is not None and pinned["manifest_sha256"] != current:
            raise ValueError("Source manifest changed after submission")
        if resolved.request.module == "flood_change" and pinned.get("comparison_manifest_sha256") != current:
            raise ValueError("Comparison source metadata changed after submission")
    if (params.get("result_snapshot") or {}) != {role: source.lineage() for role, source in resolved.upstream.items()}:
        raise ValueError("Upstream Result approval, version or artifact changed after submission")
