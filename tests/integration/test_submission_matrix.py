"""r8.1: every submit path × enforcement ON/OFF × with/without an Idempotency-Key (owner request, 2026-11-21).

The r8 defect (task_id NULL in submission_idempotency_keys with enforcement off) slipped through because every
idempotency test ran with enforcement on. This matrix runs all 12 combinations through the real routes.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.models.billing import CreditLedgerEntry, SubmissionIdempotencyKey
from app.models.platform import OrganizationEngineEntitlement, OrganizationSubscription, SubscriptionStatus
from app.models.project import Project
from app.models.task import Task, TaskStatus, TaskType
from app.services.billing import catalogue
from app.workers.celery_tasks import run_engine_analysis
from tests.integration.test_billing_credits import _payload, _tenant
from tests.integration.test_firris_bundle1 import registered_bundle

PATHS = ("analysis", "source-bound", "retry")


@pytest.fixture(autouse=True)
def _queue(monkeypatch):
    monkeypatch.setattr(run_engine_analysis, "delay", lambda task_id: SimpleNamespace(id=f"celery-{task_id}"))


def _subscribe(db, organization_id):
    """An active Researcher subscription with credits, linked to the organisation's FRRIS entitlement."""
    catalogue.seed_catalogue(db)
    subscription = OrganizationSubscription(organization_id=organization_id, plan_key="frris_wrris.researcher", family="frris_wrris",
                                            status=SubscriptionStatus.ACTIVE, starts_at=datetime.now(timezone.utc) - timedelta(days=1),
                                            source="matrix-test", monthly_credits_override=10)
    db.add(subscription)
    db.flush()
    entitlement = db.query(OrganizationEngineEntitlement).filter_by(organization_id=organization_id, engine_key="firris").one()
    entitlement.subscription_id = subscription.id
    db.commit()
    return subscription


def _setup(path, client, db, monkeypatch, tmp_path, enforcement):
    """Returns (post(headers) -> response, base headers, project id, organisation id)."""
    if path == "source-bound":
        headers, _, payload = registered_bundle(client, db, monkeypatch, tmp_path)
        project = db.get(Project, uuid.UUID(payload["project_id"]))
        if enforcement:
            _subscribe(db, project.organization_id)
        return (lambda h: client.post("/api/v1/analyses/source-bound", headers=h, json=payload)), headers, project.id, project.organization_id
    tenant = _tenant(db, f"matrix-{path}-{'on' if enforcement else 'off'}-{uuid.uuid4().hex[:6]}", credits=10, subscribed=enforcement)
    if path == "analysis":
        return (lambda h: client.post("/api/v1/analyses", headers=h, json=_payload(tenant))), tenant.headers, tenant.project.id, tenant.org.id
    failed = Task(project_id=tenant.project.id, aoi_id=tenant.aoi.id, engine_key="firris", task_type=TaskType.ANALYSIS,
                  status=TaskStatus.FAILED, input_params={"operation": "flood_mapping", "products": ["flood_depth"],
                                                          "parameters": {}, "gis_metadata": {}})
    db.add(failed)
    db.commit()
    return (lambda h: client.post(f"/api/v1/tasks/{failed.id}/retry", headers=h)), tenant.headers, tenant.project.id, tenant.org.id


def _task_id(path, response):
    body = response.json()
    return body["id"] if path == "retry" else body["task"]["id"]


@pytest.mark.parametrize("with_key", [True, False], ids=["with-key", "no-key"])
@pytest.mark.parametrize("enforcement", [True, False], ids=["enforcement-on", "enforcement-off"])
@pytest.mark.parametrize("path", PATHS)
def test_submit_paths(path, enforcement, with_key, client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", enforcement)
    post, headers, project_id, organization_id = _setup(path, client, db_session, monkeypatch, tmp_path, enforcement)
    if with_key:
        headers = {**headers, "Idempotency-Key": f"matrix-{path}-{uuid.uuid4().hex[:12]}"}
    before = {t.id for t in db_session.query(Task).filter(Task.project_id == project_id)}
    first = post(headers)
    assert first.status_code == 202, f"{path} enforcement={enforcement} key={with_key}: {first.status_code} {first.text}"
    created = {uuid.UUID(_task_id(path, first))}
    if with_key:
        again = post(headers)
        assert again.status_code == 202, again.text
        assert _task_id(path, again) == _task_id(path, first)  # the same task, not a second one
        keys = db_session.query(SubmissionIdempotencyKey).filter(SubmissionIdempotencyKey.organization_id == organization_id).all()
        assert len(keys) == 1 and keys[0].task_id == next(iter(created))
    else:
        assert db_session.query(SubmissionIdempotencyKey).filter(
            SubmissionIdempotencyKey.organization_id == organization_id).count() == 0
    db_session.expire_all()
    after = {t.id for t in db_session.query(Task).filter(Task.project_id == project_id)}
    assert after - before == created
    charges = db_session.query(CreditLedgerEntry).filter(CreditLedgerEntry.kind == "charge",
                                                         CreditLedgerEntry.task_id.in_(list(created))).count()
    assert charges == (1 if enforcement else 0)
