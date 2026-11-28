"""Q5 (decided 2026-11-21): free up storage space, and request extra storage.

(a) "Free up space": an owner or admin deletes the output files of one finished result after confirming it.
    - The result record, its summary, provenance and the analysis history stay: only the files go, so the
      storage they counted drops at once (storage counts `file_size_bytes` of output entries).
    - Each file is removed only inside the artifact root (the same containment check as downloads).
    - Each deleted entry keeps its label and a deleted marker (no path, no size), so downloads of it return 404
      and the result page lists it no longer.
    - Audited (`storage.files_deleted`, the customer as actor), never undone.
    - Owner decision 2026-11-28: the execution archive (`execution_archive`, execution-archive.json) is never
      deleted (see KEPT_OUTPUTS). It is not listed as space to free and it stays downloadable.
(b) "Request extra storage": a request to NOVA ARI like a top-up request (`subscription_requests` kind "storage",
    whole GB). The price per GB is data (`storage_extra_gb_price` in plans.v2.json), unset for now, so NOVA ARI
    quotes it.
Viewing and downloads are never blocked by storage; at 100% only new analyses are (limits.storage_blocks_submission).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.artifact_storage import artifact_root
from app.core.http import PublicAPIError
from app.models.project import Project
from app.models.result import Result
from app.services.billing import audit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredResult:
    result: Result
    project: Project
    bytes: int
    files: int


# Owner decision 2026-11-28: "Free up space" never deletes these outputs. `execution_archive`
# (execution-archive.json) is the audit/export copy of the task's execution record, so it stays with the result
# record, summary and provenance. It is a small JSON file, and it still counts towards storage used.
KEPT_OUTPUTS = frozenset({"execution_archive"})


def _deletable(key, entry) -> bool:
    return key not in KEPT_OUTPUTS and isinstance(entry, dict) and bool(entry.get("path"))


def deletable_outputs(result: Result) -> dict:
    """The output entries "Free up space" deletes: those with a file, except KEPT_OUTPUTS."""
    return {key: entry for key, entry in (result.output_files or {}).items() if _deletable(key, entry)}


def _size(entry) -> int:
    if not isinstance(entry, dict) or not entry.get("path"):
        return 0
    value = entry.get("file_size_bytes")
    return value if isinstance(value, int) and value > 0 else 0


def stored_results(db: Session, organization_id: uuid.UUID, engines: set[str], limit: int = 50) -> list[StoredResult]:
    """The organisation's results that still hold files to free (KEPT_OUTPUTS excluded), largest first (results of engines it can access)."""
    rows = (db.query(Result, Project).join(Project, Project.id == Result.project_id)
            .filter(Project.organization_id == organization_id, Result.engine_key.in_(engines or {""})).all())
    items = []
    for result, project in rows:
        if (result.summary or {}).get("status") == "running":
            continue
        entries = list(deletable_outputs(result).values())
        size = sum(_size(entry) for entry in entries)
        if entries:
            items.append(StoredResult(result, project, size, len(entries)))
    items.sort(key=lambda item: (-item.bytes, str(item.result.id)))
    return items[:limit]


def confirmation_code(result: Result) -> str:
    """What the customer types to confirm: the first 8 characters of the result ID."""
    return str(result.id)[:8]


def delete_files(db: Session, result: Result, *, confirm: str, actor: audit.Actor, organization_id: uuid.UUID) -> dict:
    """Caller has checked membership, owner/admin role, project access and engine entitlement."""
    if (confirm or "").strip().lower() != confirmation_code(result):
        raise PublicAPIError(422, "confirmation_mismatch",
                             f"Type {confirmation_code(result)} to confirm that these files will be deleted.")
    locked = db.query(Result).filter(Result.id == result.id).with_for_update().one()
    if (locked.summary or {}).get("status") == "running":
        raise PublicAPIError(409, "result_running", "This analysis is still running.")
    entries = dict(locked.output_files or {})
    targets = deletable_outputs(locked)  # never KEPT_OUTPUTS (the execution archive)
    if not targets:
        raise PublicAPIError(409, "files_already_deleted", "These files were already deleted.")
    root = artifact_root()
    now = datetime.now(timezone.utc).isoformat()
    freed, removed = 0, []
    for key, entry in sorted(targets.items()):
        path = (root / entry["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            logger.warning("Storage clean-up skipped a path outside the artifact root result=%s", locked.id)
            continue
        size = _size(entry)
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Storage clean-up could not remove a file result=%s key=%s", locked.id, key)
            raise PublicAPIError(503, "delete_failed", "The files could not be deleted. Try again later.") from None
        entries[key] = {"label": entry.get("label"), "role": entry.get("role"), "artifact_type": entry.get("artifact_type"),
                        "deleted_at": now, "deleted_bytes": size}
        freed += size
        removed.append(key)
    locked.output_files = entries
    db.flush()
    audit.record(db, actor, "storage.files_deleted", reason="Free up space: output files deleted by the customer",
                 organization_id=organization_id, target_type="result", target_id=locked.id,
                 previous={"files": sorted(targets), "bytes": sum(_size(entry) for entry in targets.values())},
                 current={"deleted": removed, "bytes_freed": freed})
    return {"result_id": str(locked.id), "files_deleted": len(removed), "bytes_freed": freed}
