"""When a charged task fails, decide whether its credit comes back (plan section 3, "Refund").

Owner decision (fix round r5, item 1, 2026-11-28): a failure caused by our system is refunded automatically.
Every refund uses the key `refund:<task_id>`, so a task is refunded at most once whatever path reaches it.

| Cause            | When                                                                     | Refund                         |
|------------------|--------------------------------------------------------------------------|--------------------------------|
| `queue_failure`  | the job never reached a worker (broker down at submission)               | always                         |
| `software_error` | any other exception while running, including FRRIS quality errors       | always                         |
|                  | outside the allow-list and provider (Earth Engine) errors                |                                |
| `time_limit`     | Celery's soft or hard time limit stopped it                              | always                         |
| `worker_lost`    | the worker child running it died (`WorkerLostError`, e.g. OOM kill)      | always                         |
| `stale_task`     | the stale-task sweeper failed it (RUNNING too long, no live worker)      | always                         |
| `data_failure`   | an allow-listed FRRIS data message (no Sentinel-1 pass, radar coverage,  | only with `refund_on_data_     |
|                  | valid coverage below the threshold)                                      | failure` on (Q3: plan default) |
| cancelled        | the user cancelled it (status CANCELED; never reaches this module)       | never                          |
| invalid input    | rejected at submission (4xx before the commit: no task, no charge)       | nothing was charged            |

Note: the legacy direct product inputs (`parameters.<product>`, extra="allow" in FIRRISAnalysisParameters) are not
typed at submission. A run that fails on a malformed one is charged and counts as `software_error`, so it is refunded.

Only a RUNNING/QUEUED -> FAILED transition reaches the refund (`_mark_failed` returns early for CANCELED, COMPLETED
and FAILED), so a completed or cancelled task is never refunded, and a late worker discards its result.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.billing import CreditLedgerEntry
from app.models.task import Task
from app.services.billing import ledger

logger = logging.getLogger(__name__)

QUEUE_FAILURE_REASON = "The analysis could not be queued, so it was not charged."
DATA_FAILURE_REASON = "Analysis stopped (not enough valid satellite data)."
STALE_TASK_REASON = "The analysis stopped because the system lost it (no worker was running it), so its credit was returned."
SOFTWARE_ERROR_REASON = "The analysis stopped because of a system error, so its credit was returned."
TIME_LIMIT_REASON = "The analysis was stopped at the system time limit, so its credit was returned."
WORKER_LOST_REASON = "The analysis stopped because the worker running it was lost, so its credit was returned."
_ALWAYS_REFUNDED = {"queue_failure": QUEUE_FAILURE_REASON, "stale_task": STALE_TASK_REASON,
                    "software_error": SOFTWARE_ERROR_REASON, "time_limit": TIME_LIMIT_REASON,
                    "worker_lost": WORKER_LOST_REASON}


def is_data_failure(error: BaseException) -> bool:
    from app.services.firris.user_messages import GENERIC_FAILURE, public_error_summary

    try:
        return public_error_summary(error) != GENERIC_FAILURE
    except Exception:  # classification must never break failure handling
        return False


def failure_cause(error: BaseException) -> str:
    """The refund cause of a run failure (see the table above). Never raises."""
    from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded, WorkerLostError

    from app.services.tasks.failures import WorkerTimeLimitError
    from app.services.tasks.stale_sweeper import StaleTaskError

    if isinstance(error, StaleTaskError):
        return "stale_task"
    if isinstance(error, (WorkerTimeLimitError, TimeLimitExceeded, SoftTimeLimitExceeded)):
        return "time_limit"
    if isinstance(error, WorkerLostError):
        return "worker_lost"
    return "data_failure" if is_data_failure(error) else "software_error"


def refund_failed_task(db: Session, task: Task, *, cause: str) -> CreditLedgerEntry | None:
    """Write the refund in the caller's transaction (inside a savepoint), or nothing. Never raises."""
    charge = ledger.entry_by_key(db, f"charge:{task.id}")
    if charge is None:
        return None
    try:
        with db.begin_nested():
            subscription = ledger.lock_subscription(db, charge.subscription_id)
            if cause == "data_failure" and not ledger.refund_on_data_failure(db, subscription):
                return None
            if cause not in {*_ALWAYS_REFUNDED, "data_failure"}:
                return None
            reason = _ALWAYS_REFUNDED.get(cause, DATA_FAILURE_REASON)
            return ledger.refund_task(db, subscription, task.id, reason=reason, cause=cause)
    except Exception:
        logger.exception("Credit refund failed for task %s; NOVA ARI can refund it with an adjustment.", task.id)
        return None
