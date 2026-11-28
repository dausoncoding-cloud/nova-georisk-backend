"""Fix round r5, item 1 (owner decision 2026-11-28): failures caused by our system are refunded automatically, once,
with the key refund:<task id>. Invalid input is never charged; a cancelled task is never refunded. The cause table
is in app/services/billing/refunds.py."""
import pytest
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded, WorkerLostError
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.billing import CreditLedgerEntry
from app.models.task import Task, TaskStatus
from app.services.billing import ledger, refunds
from app.services.gee.firris_pipeline import FIRRISQualityError
from app.services.tasks.failures import WorkerTimeLimitError
from app.workers import celery_tasks
from tests.integration.test_billing_credits import (DATA_FAILURE, _entries, _failed_charged_task, _payload,  # noqa: F401
                                                    _queue, _tenant)

SYSTEM_FAILURES = {
    "software-error": (RuntimeError("Earth Engine internal error"), "software_error", refunds.SOFTWARE_ERROR_REASON),
    "quality-error-outside-allow-list": (FIRRISQualityError("unexpected raster shape"), "software_error",
                                         refunds.SOFTWARE_ERROR_REASON),
    "hard-time-limit": (WorkerTimeLimitError("Worker hard time limit exceeded"), "time_limit", refunds.TIME_LIMIT_REASON),
    "celery-time-limit": (TimeLimitExceeded(14400), "time_limit", refunds.TIME_LIMIT_REASON),
    "soft-time-limit": (SoftTimeLimitExceeded(), "time_limit", refunds.TIME_LIMIT_REASON),
    "lost-worker-child": (WorkerLostError("Worker exited prematurely: signal 9 (SIGKILL)."), "worker_lost",
                          refunds.WORKER_LOST_REASON),
}


@pytest.fixture(autouse=True)
def enforced(monkeypatch, engine):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)
    monkeypatch.setattr(celery_tasks, "SessionLocal", sessionmaker(bind=engine))  # the parent bridge's own session


def _refunds(db, t):
    db.expire_all()
    return _entries(db, t.sub, "refund")


@pytest.mark.parametrize("path", ["in-task", "parent-bridge"])
@pytest.mark.parametrize("case", sorted(SYSTEM_FAILURES))
def test_a_system_failure_is_refunded_once_with_its_cause(client, db_session, case, path):
    error, cause, reason = SYSTEM_FAILURES[case]
    t = _tenant(db_session, f"rp-{case}-{path}"[:60], credits=5)
    task = _failed_charged_task(client, db_session, t)
    if path == "in-task":  # the exception inside the task (execute_engine_task's handler)
        celery_tasks._mark_failed(db_session, task, error)
    else:  # FIRRISRequest.on_timeout / on_failure in the Celery parent
        celery_tasks.persist_worker_failure(task.id, error)
    rows = _refunds(db_session, t)
    assert len(rows) == 1, case
    refund = rows[0]
    assert (refund.task_id, refund.idempotency_key, refund.reason) == (task.id, f"refund:{task.id}", reason)
    assert refund.metadata_json == {"cause": cause}
    assert db_session.get(Task, task.id).status == TaskStatus.FAILED
    # Any later path (a second failure report, the bridge, a direct refund call) never refunds again.
    celery_tasks.persist_worker_failure(task.id, WorkerLostError("again"))
    celery_tasks._mark_failed(db_session, db_session.get(Task, task.id), RuntimeError("again"))
    refunds.refund_failed_task(db_session, db_session.get(Task, task.id), cause=cause)
    db_session.commit()
    assert len(_refunds(db_session, t)) == 1
    assert ledger.balances(db_session, t.sub.id).total == 5


def test_the_hard_time_limit_and_a_lost_child_reach_the_refund_through_the_celery_request(monkeypatch):
    """The parent-side hooks pass the classified errors (no broker, no database: the bridge is captured)."""
    from celery.worker.request import Request
    seen = []
    monkeypatch.setattr(celery_tasks, "persist_worker_failure", lambda task_id, error: seen.append((task_id, error)))
    monkeypatch.setattr(Request, "on_timeout", lambda self, soft, timeout: None)
    monkeypatch.setattr(Request, "on_failure", lambda self, exc_info, send_failed_event=True, return_ok=False: None)
    request = celery_tasks.FIRRISRequest.__new__(celery_tasks.FIRRISRequest)
    monkeypatch.setattr(celery_tasks.FIRRISRequest, "args", ["task-1"], raising=False)
    request.on_timeout(False, 14400)
    request.on_timeout(True, 14000)  # soft: the task itself raises SoftTimeLimitExceeded, handled in-task
    lost = WorkerLostError("Worker exited prematurely: signal 9 (SIGKILL).")
    request.on_failure(type("ExcInfo", (), {"exception": lost})())
    assert [refunds.failure_cause(error) for _, error in seen] == ["time_limit", "worker_lost"]


def test_data_failures_still_follow_the_plan_flag(client, db_session):
    t = _tenant(db_session, "rp-data", credits=5)
    t.sub.refund_on_data_failure_override = False
    db_session.commit()
    task = _failed_charged_task(client, db_session, t)
    celery_tasks._mark_failed(db_session, task, FIRRISQualityError(DATA_FAILURE))
    assert refunds.failure_cause(FIRRISQualityError(DATA_FAILURE)) == "data_failure" and _refunds(db_session, t) == []


def test_a_cancelled_task_is_never_refunded(client, db_session):
    t = _tenant(db_session, "rp-cancel", credits=5)
    task = _failed_charged_task(client, db_session, t)
    assert client.post(f"/api/v1/tasks/{task.id}/cancel", headers=t.headers).status_code == 200
    # A late failure report (a system failure) after the cancel still never refunds.
    celery_tasks.persist_worker_failure(task.id, WorkerLostError("late"))
    celery_tasks._mark_failed(db_session, db_session.get(Task, task.id), RuntimeError("late"))
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == TaskStatus.CANCELED and _refunds(db_session, t) == []
    assert len(_entries(db_session, t.sub, "charge")) == 1 and ledger.balances(db_session, t.sub.id).total == 4


@pytest.mark.parametrize("case", ["unknown-product", "duplicate-product", "no-product", "bad-workflow"])
def test_input_rejected_at_submission_is_never_charged(client, db_session, case):
    """Input the submission schema rejects (4xx before the commit) creates no task and no charge. Note: the legacy
    direct product inputs (`parameters.flood_depth` ...) are not typed at submission (extra="allow"); a run that
    fails on them is charged and, under r5-1, refunded as a software error (refunds.py table)."""
    t = _tenant(db_session, f"rp-invalid-{case}", credits=5)
    bad = _payload(t)
    if case == "unknown-product":
        bad["products"] = ["not_a_product"]
    elif case == "duplicate-product":
        bad["products"] = ["flood_depth", "flood_depth"]
    elif case == "no-product":
        bad["products"] = []
    else:
        bad["parameters"]["workflow"] = {"source": "not a workflow"}
    response = client.post("/api/v1/analyses", headers=t.headers, json=bad)
    assert 400 <= response.status_code < 500, response.text
    assert db_session.query(Task).filter(Task.project_id == t.project.id).count() == 0
    assert db_session.query(CreditLedgerEntry).filter(CreditLedgerEntry.subscription_id == t.sub.id,
                                                      CreditLedgerEntry.kind.in_(["charge", "refund"])).count() == 0
