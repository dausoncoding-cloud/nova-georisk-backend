"""r12: stale RUNNING-task sweeper (more than 4 h RUNNING, no live worker), with billing enforcement on and off."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.services.firris.user_messages import GENERIC_FAILURE
from app.services.tasks import stale_sweeper
from app.workers import celery_tasks
from tests.integration.test_billing_credits import _entries, _failed_charged_task, _tenant  # noqa: F401  (fixtures)
from tests.integration.test_billing_credits import _queue  # noqa: F401  (autouse: no broker in tests)


@pytest.fixture(autouse=True)
def _bridge(monkeypatch, engine, tmp_path):
    monkeypatch.setattr(celery_tasks, "SessionLocal", sessionmaker(bind=engine))  # the bridge's own session
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    monkeypatch.setattr(stale_sweeper, "_live_cache", None)
    live = {"ids": frozenset()}
    monkeypatch.setattr(stale_sweeper, "live_task_ids", lambda: live["ids"])
    return live


@pytest.fixture()
def enforced(monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)


@pytest.fixture()
def unenforced(monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", False)


def _subscribed() -> bool:
    """The suite runs with enforcement ON and OFF (NOVA_TEST_BILLING_ENFORCEMENT, tests/conftest.py). With it ON a
    submission needs an Active subscription (402 subscription_required otherwise, as in production after Phase B),
    so the tenant is subscribed exactly when enforcement is on; the sweeper behaviour under test is the same."""
    return get_settings().billing_enforcement_enabled


def _stale(client, db, t, tmp_path, *, hours=5.0):
    """A charged (when enforced) RUNNING task with a reserved half-written result and its output folder."""
    task = _failed_charged_task(client, db, t)
    task.started_at = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = Result(task_id=task.id, engine_key="firris", project_id=task.project_id, aoi_id=task.aoi_id,
                    result_type="firris", summary={"status": "running"})
    db.add(result)
    db.commit()
    folder = tmp_path / str(task.project_id) / str(task.aoi_id) / str(result.id)
    folder.mkdir(parents=True)
    (folder / "partial.tif").write_bytes(b"partial")
    return task, result.id, folder


def _assert_swept(db, task, result_id, folder):
    db.expire_all()
    task = db.get(Task, task.id)
    assert task.status == TaskStatus.FAILED
    assert task.error_summary == GENERIC_FAILURE  # the same user-visible message as other failures
    assert stale_sweeper.STALE_REASON in task.error_message  # the cause stays server-side
    assert task.result_payload["execution_record"]["events"][-1]["action"] == "failed"  # hash-chained audit trail
    assert db.get(Result, result_id) is None and not folder.exists()
    return task


def test_enforced_stale_task_is_failed_cleaned_and_keeps_the_software_error_refund_policy(client, db_session, enforced, tmp_path):
    t = _tenant(db_session, "sweep-on", credits=5)
    task, result_id, folder = _stale(client, db_session, t, tmp_path)
    assert len(_entries(db_session, t.sub, "charge")) == 1
    body = client.get(f"/api/v1/tasks/{task.id}", headers=t.headers).json()
    assert body["status"] == "failed" and body["error_summary"] == GENERIC_FAILURE
    _assert_swept(db_session, task, result_id, folder)
    assert _entries(db_session, t.sub, "refund") == []  # software error: no automatic refund (policy unchanged)
    assert len(_entries(db_session, t.sub, "charge")) == 1


def test_unenforced_stale_task_is_swept_from_the_task_list_with_no_ledger_entries(client, db_session, unenforced, tmp_path):
    t = _tenant(db_session, "sweep-off", subscribed=False)  # enforcement pinned OFF (fixture)
    task, result_id, folder = _stale(client, db_session, t, tmp_path)
    assert client.get("/api/v1/tasks", headers=t.headers).status_code == 200
    _assert_swept(db_session, task, result_id, folder)
    from app.models.billing import CreditLedgerEntry
    assert db_session.query(CreditLedgerEntry).count() == 0


@pytest.mark.parametrize("case", ["recent", "live", "liveness_unknown"])
def test_tasks_that_may_still_run_are_never_swept(client, db_session, tmp_path, _bridge, case):
    t = _tenant(db_session, f"sweep-keep-{case.replace('_', '-')}", subscribed=_subscribed())
    task, result_id, folder = _stale(client, db_session, t, tmp_path, hours=3.5 if case == "recent" else 5.0)
    if case == "live":
        _bridge["ids"] = frozenset({str(task.id)})
    if case == "liveness_unknown":
        _bridge["ids"] = None
    assert client.get(f"/api/v1/tasks/{task.id}", headers=t.headers).json()["status"] == "running"
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == TaskStatus.RUNNING
    assert db_session.get(Result, result_id) is not None and folder.exists()


def test_a_request_only_sweeps_its_own_organization(client, db_session, tmp_path):
    a = _tenant(db_session, "sweep-org-a", subscribed=_subscribed())
    b = _tenant(db_session, "sweep-org-b", subscribed=_subscribed())
    task_b, result_b, folder_b = _stale(client, db_session, b, tmp_path)
    assert client.get("/api/v1/tasks", headers=a.headers).status_code == 200
    db_session.expire_all()
    assert db_session.get(Task, task_b.id).status == TaskStatus.RUNNING and folder_b.exists()
    assert client.get("/api/v1/tasks", headers=b.headers).status_code == 200
    _assert_swept(db_session, task_b, result_b, folder_b)


def test_a_stale_task_no_longer_holds_the_organization_capacity(client, db_session, tmp_path, monkeypatch):
    from tests.integration.test_billing_credits import _payload
    t = _tenant(db_session, "sweep-capacity", subscribed=_subscribed())
    task, result_id, folder = _stale(client, db_session, t, tmp_path)
    monkeypatch.setattr(get_settings(), "firris_max_pending_tasks_per_organization", 1)
    response = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t))
    assert response.status_code == 202, response.text  # was 429 while the dead task counted as pending
    _assert_swept(db_session, task, result_id, folder)
    assert uuid.UUID(response.json()["task"]["id"]) != task.id


def test_repeated_sweeps_do_not_append_events_twice(client, db_session, tmp_path):
    t = _tenant(db_session, "sweep-twice", subscribed=_subscribed())
    task, result_id, folder = _stale(client, db_session, t, tmp_path)
    client.get("/api/v1/tasks", headers=t.headers)
    events = len(_assert_swept(db_session, task, result_id, folder).result_payload["execution_record"]["events"])
    client.get("/api/v1/tasks", headers=t.headers)
    db_session.expire_all()
    assert len(db_session.get(Task, task.id).result_payload["execution_record"]["events"]) == events
