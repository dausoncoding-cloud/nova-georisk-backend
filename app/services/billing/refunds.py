"""When a charged task fails, decide whether its credit comes back (plan section 3, "Refund").

- `queue_failure`: the job never reached a worker, so it was never really submitted; always refunded.
- `data_failure`: only the allow-listed FRRIS data messages (no Sentinel-1 pass, radar coverage, valid
  coverage below the threshold); refunded only when `refund_on_data_failure` is on (default off, Q3).
- `stale_task`: the r12 stale-task sweeper failed it (RUNNING beyond the stale limit with no live worker): the system
  lost it, so it is always refunded (security review round 4, item 2). The sweep only moves RUNNING to FAILED, and a
  late worker then discards its own result, so a COMPLETED task is never refunded;
- anything else is a software error: NOVA ARI investigates and refunds manually with an adjustment.
At most one refund per task (`refund:<task_id>`).
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
_ALWAYS_REFUNDED = {"queue_failure": QUEUE_FAILURE_REASON, "stale_task": STALE_TASK_REASON}


def is_data_failure(error: BaseException) -> bool:
    from app.services.firris.user_messages import GENERIC_FAILURE, public_error_summary

    try:
        return public_error_summary(error) != GENERIC_FAILURE
    except Exception:  # classification must never break failure handling
        return False


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
