"""Stale RUNNING-task sweeper (r12, owner decision 2026-11-27).

If the worker's main process dies (for example an out-of-memory kill of the Celery parent), the parent-side failure
bridge (``persist_worker_failure``) never runs: the task stays RUNNING for good, the redelivered message is refused
because the task is no longer QUEUED, and the task keeps counting against the organization's pending-task cap.

FRRIS tasks are swept when BOTH hold:
  * it has been RUNNING for more than the stale-running setting (default 4 h, equal to the hard time limit, so
    a live execution would already have been stopped and failed by Celery); and
  * no live worker reports it as executing (Celery ``inspect active``). If the broker cannot be asked, nothing is swept.

A swept task goes through the same path as a lost worker child (``persist_worker_failure``): status FAILED, the
reserved (half-written) result row and its output folder removed, the same generic user-visible message, the
``failed`` event appended to the task's hash-chained execution record (its audit trail). The credit is returned
automatically (``refund_failed_task`` with the ``stale_task`` cause, key ``refund:<task id>``, at most once; security
review round 4, item 2): the system lost the task. A worker that finishes after the sweep finds the task no longer
RUNNING and discards its own result, so the refund stays consistent; a COMPLETED task is never swept.

Callers pass the organization of the request, so a user's request only ever sweeps that organization's tasks.
The operator CLI (``python -m app.services.tasks.stale_sweeper``) sweeps every organization.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.models.project import Project
from app.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)

STALE_REASON = "Task was RUNNING beyond the stale-task limit with no live worker (stale-task sweeper)"
INSPECT_TIMEOUT_S = 3.0
_LIVE_CACHE_S = 60.0
_live_cache: tuple[float, frozenset[str]] | None = None


class StaleTaskError(RuntimeError):
    """Recorded server-side as the failure cause; users see the generic failure message."""


def stale_candidates(db, organization_id: uuid.UUID | None, now: datetime | None = None) -> list[Task]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(seconds=get_settings().firris_stale_running_seconds)
    query = db.query(Task).filter(Task.engine_key == "firris", Task.status == TaskStatus.RUNNING,
                                  Task.started_at.is_not(None), Task.started_at < cutoff)
    if organization_id is not None:
        query = query.join(Project, Task.project_id == Project.id).filter(Project.organization_id == organization_id)
    return query.all()


def live_task_ids() -> frozenset[str] | None:
    """Task ids (our database ids, the task's first argument) executing on any live worker; None if unknown."""
    global _live_cache
    if _live_cache is not None and time.monotonic() - _live_cache[0] < _LIVE_CACHE_S:
        return _live_cache[1]
    try:
        from app.core.celery_app import celery_app
        active = celery_app.control.inspect(timeout=INSPECT_TIMEOUT_S).active()
    except Exception:  # noqa: BLE001 - broker unreachable: liveness unknown, so sweep nothing
        logger.warning("Stale-task sweep skipped: worker liveness could not be checked", exc_info=True)
        return None
    ids = frozenset(str(request["args"][0]) for requests in (active or {}).values() for request in requests or []
                    if request.get("args"))
    _live_cache = (time.monotonic(), ids)
    return ids


def sweep(db, organization_id: uuid.UUID | None, *, now: datetime | None = None, live=None) -> list[uuid.UUID]:
    """Fail the organization's stale RUNNING FRRIS tasks that no live worker is executing. Never raises."""
    try:
        candidates = stale_candidates(db, organization_id, now)
        if not candidates:
            return []
        running = (live or live_task_ids)()
        if running is None:
            return []
        from app.workers.celery_tasks import persist_worker_failure  # light module (see its header)
        swept = []
        for task in candidates:
            if str(task.id) in running:
                continue
            logger.warning("Stale-task sweeper: failing task_id=%s organization_id=%s started_at=%s",
                           task.id, organization_id or "all", task.started_at.isoformat())
            persist_worker_failure(task.id, StaleTaskError(STALE_REASON))
            db.expire(task)  # the bridge committed in its own session; never expire the caller's other pending work
            swept.append(task.id)
        return swept
    except Exception:  # noqa: BLE001 - a sweep must never break the request that triggered it
        logger.exception("Stale-task sweep failed")
        return []


if __name__ == "__main__":  # operator use: python -m app.services.tasks.stale_sweeper
    from app.db.session import SessionLocal
    session = SessionLocal()
    try:
        print({"swept": [str(task_id) for task_id in sweep(session, None)]})
    finally:
        session.close()
