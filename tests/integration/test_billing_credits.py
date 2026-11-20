"""Subscriptions M1: catalogue seed, charge on submit, idempotency, hard stop, refunds, monthly grant, thresholds."""
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.http import PublicAPIError
from app.core.security import OrganizationRole, RequestContext
from app.models.aoi import AOI
from app.models.billing import BillingPlanPrice, CreditLedgerEntry, CreditUsageNotice, SubmissionIdempotencyKey
from app.models.identity import MembershipRole, Organization, OrganizationMembership, User
from app.models.platform import (BillingPlan, EntitlementStatus, OrganizationEngineEntitlement,
                                 OrganizationSubscription, SubscriptionStatus)
from app.models.project import Project
from app.models.task import Task, TaskStatus, TaskType
from app.services.billing import catalogue, ledger, refunds
from app.services.billing.submission import SubmissionCharge
from app.workers.celery_tasks import _mark_failed, run_engine_analysis

DATA_FAILURE = "Valid pixel coverage 50.00% is below the configured 70.00% threshold."


@pytest.fixture()
def enforced(monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", True)


@pytest.fixture(autouse=True)
def _queue(monkeypatch):
    monkeypatch.setattr(run_engine_analysis, "delay", lambda task_id: SimpleNamespace(id=f"celery-{task_id}"))


def _tenant(db, slug, *, credits=None, status=SubscriptionStatus.ACTIVE, subscribed=True,
            role=MembershipRole.OWNER, plan_key="frris_wrris.researcher"):
    catalogue.seed_catalogue(db)
    organization = Organization(name=slug.title(), slug=slug)
    user = User(issuer="https://identity.billing.test/", subject=str(uuid.uuid4()), email=f"{slug}@example.test")
    db.add_all([organization, user])
    db.flush()
    subscription = None
    if subscribed:
        subscription = OrganizationSubscription(
            organization_id=organization.id, plan_key=plan_key, family="frris_wrris", status=status,
            starts_at=datetime.now(timezone.utc) - timedelta(days=1), source="billing-test",
            monthly_credits_override=credits)
        db.add(subscription)
        db.flush()
    db.add_all([
        OrganizationMembership(organization_id=organization.id, user_id=user.id, role=role),
        OrganizationEngineEntitlement(organization_id=organization.id, engine_key="firris",
                                      status=EntitlementStatus.ACTIVE, source="billing-test",
                                      subscription_id=subscription.id if subscription else None),
    ])
    project = Project(name="Billing", organization_id=organization.id, engine_key="firris", analysis_module="FIRRIS")
    db.add(project)
    db.flush()
    aoi = AOI(project_id=project.id, name="Area", source_type="drawn_polygon",
              geometry=WKTElement("MULTIPOLYGON(((36 -2,37 -2,37 -1,36 -1,36 -2)))", srid=4326),
              area_m2=1.0, area_hectares=0.0001, area_km2=0.000001, perimeter_m=4.0)
    db.add(aoi)
    db.commit()
    headers = {"X-Nova-User-Id": str(user.id), "X-Nova-Organization-Id": str(organization.id),
               "X-Nova-Role": role.value}
    return SimpleNamespace(org=organization, user=user, sub=subscription, project=project, aoi=aoi, headers=headers)


def _payload(t, depth=5.0):
    return {
        "project_id": str(t.project.id), "aoi_id": str(t.aoi.id), "products": ["flood_depth"],
        "parameters": {"flood_depth": {"water_surface_elevation": [depth, 3.0], "ground_elevation": [3.5, 4.0]}},
        "gis_metadata": {"crs": "EPSG:4326", "datum": "WGS 84", "projection": "Geographic",
                         "bounding_box": {"west": 36, "south": -2, "east": 37, "north": -1},
                         "spatial_resolution": {"x": 10, "y": 10, "unit": "m"}, "acquisition_date": "2026-09-28"},
    }


def _entries(db, sub, kind=None):
    query = db.query(CreditLedgerEntry).filter(CreditLedgerEntry.subscription_id == sub.id)
    if kind:
        query = query.filter(CreditLedgerEntry.kind == kind)
    return query.order_by(CreditLedgerEntry.created_at).all()


def _tasks(db, t):
    return db.query(Task).filter(Task.project_id == t.project.id).all()


def _failed_charged_task(client, db, t):
    response = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t))
    assert response.status_code == 202, response.text
    task = db.get(Task, uuid.UUID(response.json()["task"]["id"]))
    task.status = TaskStatus.RUNNING
    db.commit()
    return task


def test_catalogue_seed_matches_data_file_and_is_idempotent(db_session):
    first = catalogue.seed_catalogue(db_session)
    db_session.commit()
    assert len(first.plans) == 12 and len(first.prices) == 12
    again = catalogue.seed_catalogue(db_session)
    assert again.plans == [] and again.prices == [] and again.engine_links == []
    researcher = db_session.get(BillingPlan, "frris_wrris.researcher")
    assert (researcher.monthly_credits, researcher.seat_limit, researcher.session_limit) == (10, 1, 1)
    assert researcher.refund_on_data_failure is False  # Q3: off until the client confirms
    price = db_session.query(BillingPlanPrice).filter_by(plan_key="frris_wrris.researcher").one()
    assert (price.monthly_price, price.top_up_credit_price, price.currency) == (150000, 10000, "TZS")
    assert db_session.query(BillingPlanPrice).filter_by(plan_key="megis.researcher").one().top_up_credit_price is None
    assert db_session.get(BillingPlan, "frris_wrris.custom").monthly_credits is None


def test_submission_charges_one_credit_in_the_same_transaction(client, db_session, enforced):
    t = _tenant(db_session, "billing-charge", credits=2)
    response = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t))
    assert response.status_code == 202, response.text
    task_id = uuid.UUID(response.json()["task"]["id"])
    charge = _entries(db_session, t.sub, "charge")
    assert len(charge) == 1 and charge[0].task_id == task_id and charge[0].amount == -1
    assert charge[0].idempotency_key == f"charge:{task_id}" and charge[0].bucket == "monthly"
    assert ledger.balances(db_session, t.sub.id).total == 1
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]
    assert summary["credits"] == {"period": ledger.period_of(), "granted": 2, "top_ups": 0, "used": 1,
                                        "remaining": 1, "available": 2, "used_percent": 50.0, "level": None}
    assert summary["can_submit"] is True and summary["plan_name"] == "Researcher"


def test_no_credits_is_a_hard_stop_on_new_analyses_only(client, db_session, enforced):
    t = _tenant(db_session, "billing-stop", credits=1)
    assert client.post("/api/v1/analyses", headers=t.headers, json=_payload(t)).status_code == 202
    blocked = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t, depth=6.0))
    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "credits_exhausted"
    assert blocked.json()["detail"] == "No credits left. Contact your administrator or NOVA ARI to top up."
    assert len(_tasks(db_session, t)) == 1 and len(_entries(db_session, t.sub, "charge")) == 1
    # Reading continues: task list, task detail, archive, summary and ledger.
    task_id = _tasks(db_session, t)[0].id
    assert client.get("/api/v1/tasks", headers=t.headers).status_code == 200
    assert client.get(f"/api/v1/tasks/{task_id}", headers=t.headers).status_code == 200
    assert client.get(f"/api/v1/tasks/{task_id}/archive", headers=t.headers).status_code == 200
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]
    assert summary["can_submit"] is False and summary["block_code"] == "credits_exhausted"
    assert summary["credits"]["level"] == 100
    assert client.get("/api/v1/billing/ledger", headers=t.headers).json()["total"] == 2


def test_idempotency_key_never_creates_a_second_task_or_charge(client, db_session, enforced):
    t = _tenant(db_session, "billing-idem", credits=5)
    headers = {**t.headers, "Idempotency-Key": "submit-0001-abcdef"}
    first = client.post("/api/v1/analyses", headers=headers, json=_payload(t))
    second = client.post("/api/v1/analyses", headers=headers, json=_payload(t))
    assert first.status_code == second.status_code == 202
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert len(_tasks(db_session, t)) == 1 and len(_entries(db_session, t.sub, "charge")) == 1
    reused = client.post("/api/v1/analyses", headers=headers, json=_payload(t, depth=9.0))
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "idempotency_key_reused"
    bad = client.post("/api/v1/analyses", headers={**t.headers, "Idempotency-Key": "x"}, json=_payload(t))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "idempotency_key_invalid"
    assert db_session.query(SubmissionIdempotencyKey).count() == 1


def test_idempotency_keys_are_scoped_to_the_user_and_organisation(client, db_session, enforced):
    a = _tenant(db_session, "billing-idem-a", credits=5)
    b = _tenant(db_session, "billing-idem-b", credits=5)
    key = "shared-key-123456"
    first = client.post("/api/v1/analyses", headers={**a.headers, "Idempotency-Key": key}, json=_payload(a))
    other = client.post("/api/v1/analyses", headers={**b.headers, "Idempotency-Key": key}, json=_payload(b))
    assert first.status_code == other.status_code == 202
    assert first.json()["task"]["id"] != other.json()["task"]["id"]


def test_parallel_submissions_cannot_both_spend_the_last_credit(engine, db_session, enforced):
    t = _tenant(db_session, "billing-race", credits=1)
    context = RequestContext(role=OrganizationRole.OWNER, user_id=t.user.id, organization_id=t.org.id)
    Session = sessionmaker(bind=engine)
    barrier, outcomes = threading.Barrier(2), []

    def submit():
        session = Session()
        try:
            barrier.wait()
            charge = SubmissionCharge.reserve(session, context, "firris")
            task = Task(project_id=t.project.id, aoi_id=t.aoi.id, engine_key="firris", task_type=TaskType.ANALYSIS,
                        status=TaskStatus.QUEUED, input_params={})
            session.add(task)
            charge.charge(session, task)
            session.commit()
            outcomes.append("charged")
        except PublicAPIError as exc:
            session.rollback()
            outcomes.append(exc.code)
        finally:
            session.close()

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    db_session.expire_all()
    assert sorted(outcomes) == ["charged", "credits_exhausted"]
    assert len(_entries(db_session, t.sub, "charge")) == 1
    assert ledger.balances(db_session, t.sub.id).total == 0


def test_retry_is_charged_like_a_new_submission(client, db_session, enforced):
    t = _tenant(db_session, "billing-retry", credits=3)
    failed = Task(project_id=t.project.id, aoi_id=t.aoi.id, engine_key="firris", task_type=TaskType.ANALYSIS,
                  status=TaskStatus.FAILED, input_params={"operation": "flood_mapping", "products": ["flood_depth"],
                                                          "parameters": {}, "gis_metadata": {}})
    db_session.add(failed)
    db_session.commit()
    headers = {**t.headers, "Idempotency-Key": "retry-key-000001"}
    retried = client.post(f"/api/v1/tasks/{failed.id}/retry", headers=headers)
    again = client.post(f"/api/v1/tasks/{failed.id}/retry", headers=headers)
    assert retried.status_code == again.status_code == 202
    assert retried.json()["id"] == again.json()["id"]
    charges = _entries(db_session, t.sub, "charge")
    assert len(charges) == 1 and str(charges[0].task_id) == retried.json()["id"]


def test_status_blocks_new_analyses_with_402_and_keeps_reading(client, db_session, enforced):
    t = _tenant(db_session, "billing-suspended", credits=5, status=SubscriptionStatus.SUSPENDED)
    blocked = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t))
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "subscription_suspended"
    assert blocked.json()["detail"] == "Account suspended: contact NOVA ARI."
    assert client.get("/api/v1/tasks", headers=t.headers).status_code == 200
    summary = client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]
    assert summary["status_label"] == "Suspended" and summary["can_submit"] is False
    assert summary["credits"]["granted"] == 0  # no grant while suspended

    none = _tenant(db_session, "billing-unsubscribed", subscribed=False)
    missing = client.post("/api/v1/analyses", headers=none.headers, json=_payload(none))
    assert missing.status_code == 402 and missing.json()["error"]["code"] == "subscription_required"
    assert _tasks(db_session, t) == [] and _tasks(db_session, none) == []


def test_enforcement_off_keeps_todays_behaviour(client, db_session):
    t = _tenant(db_session, "billing-off", subscribed=False)
    assert client.post("/api/v1/analyses", headers=t.headers, json=_payload(t)).status_code == 202
    assert db_session.query(CreditLedgerEntry).count() == 0
    assert client.get("/api/v1/billing/summary", headers=t.headers).json() == {
        "enforcement_enabled": False, "subscriptions": []}


def test_data_failure_refund_only_when_the_flag_is_on_and_at_most_once(client, db_session, enforced):
    from app.services.gee.firris_pipeline import FIRRISQualityError

    t = _tenant(db_session, "billing-refund", credits=5)
    off = _failed_charged_task(client, db_session, t)
    _mark_failed(db_session, off, FIRRISQualityError(DATA_FAILURE))
    assert _entries(db_session, t.sub, "refund") == []  # flag defaults to off (Q3)

    t.sub.refund_on_data_failure_override = True
    db_session.commit()
    on = _failed_charged_task(client, db_session, t)
    _mark_failed(db_session, on, FIRRISQualityError(DATA_FAILURE))
    refunds.refund_failed_task(db_session, on, cause="data_failure")
    db_session.commit()
    refund = _entries(db_session, t.sub, "refund")
    assert len(refund) == 1 and refund[0].task_id == on.id and refund[0].idempotency_key == f"refund:{on.id}"

    software = _failed_charged_task(client, db_session, t)
    _mark_failed(db_session, software, RuntimeError("Earth Engine internal error"))
    assert len(_entries(db_session, t.sub, "refund")) == 1  # software errors are refunded manually
    assert ledger.balances(db_session, t.sub.id).total == 5 - 3 + 1


def test_queue_failure_is_refunded_even_with_the_flag_off(client, db_session, enforced, monkeypatch):
    t = _tenant(db_session, "billing-queue", credits=2)

    def broken(_task_id):
        raise RuntimeError("broker down")
    monkeypatch.setattr(run_engine_analysis, "delay", broken)
    response = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t))
    assert response.status_code == 503
    assert len(_entries(db_session, t.sub, "charge")) == 1 and len(_entries(db_session, t.sub, "refund")) == 1
    assert ledger.balances(db_session, t.sub.id).total == 2


def test_monthly_grant_runs_once_per_month_and_unused_credits_expire(db_session, monkeypatch):
    t = _tenant(db_session, "billing-grant", credits=10)
    now = datetime.now(timezone.utc)
    sub = ledger.lock_subscription(db_session, t.sub.id)
    for _ in range(3):
        ledger.ensure_period(db_session, sub, now)
    ledger.append_entry(db_session, sub, kind="top_up", bucket="top_up", amount=10, key="topup:test")
    db_session.commit()
    assert len(_entries(db_session, t.sub, "monthly_grant")) == 1
    next_month = now + timedelta(days=32)
    sub = ledger.lock_subscription(db_session, t.sub.id)
    ledger.ensure_period(db_session, sub, next_month)
    ledger.ensure_period(db_session, sub, next_month)
    db_session.commit()
    grants = _entries(db_session, t.sub, "monthly_grant")
    assert [g.period for g in grants] == [ledger.period_of(now), ledger.period_of(next_month)]
    expiry = _entries(db_session, t.sub, "expiry")
    assert len(expiry) == 1 and expiry[0].amount == -10 and expiry[0].bucket == "monthly"
    assert ledger.balances(db_session, t.sub.id) == ledger.Balances(monthly=10, top_up=10)  # top-ups kept

    monkeypatch.setattr(get_settings(), "billing_monthly_credits_roll_over", True)
    sub = ledger.lock_subscription(db_session, t.sub.id)
    ledger.ensure_period(db_session, sub, now + timedelta(days=64))
    db_session.commit()
    assert ledger.balances(db_session, t.sub.id).monthly == 20


def test_warnings_at_75_90_and_100_percent_are_recorded_once_per_month(client, db_session, enforced):
    t = _tenant(db_session, "billing-thresholds", credits=10)
    levels = []
    for index in range(10):
        response = client.post("/api/v1/analyses", headers=t.headers, json=_payload(t, depth=10.0 + index))
        assert response.status_code == 202
        levels.append(client.get("/api/v1/billing/summary", headers=t.headers).json()["subscriptions"][0]["credits"]["level"])
    assert levels == [None] * 7 + [75, 90, 100]  # 8/10 = 80%, 9/10 = 90%, 10/10
    notices = db_session.query(CreditUsageNotice).filter_by(subscription_id=t.sub.id).all()
    assert sorted(n.level for n in notices) == [75, 90, 100]


def test_ledger_rows_are_append_only(db_session):
    t = _tenant(db_session, "billing-immutable", credits=3)
    sub = ledger.lock_subscription(db_session, t.sub.id)
    ledger.ensure_period(db_session, sub)
    db_session.commit()
    for statement in ("UPDATE credit_ledger_entries SET amount = 99", "DELETE FROM credit_ledger_entries",
                      "UPDATE billing_plan_prices SET monthly_price = 1"):
        with pytest.raises(DBAPIError, match="append-only"):
            db_session.execute(text(statement))
        db_session.rollback()
    with pytest.raises(ledger.LedgerError, match="reason"):
        ledger.append_entry(db_session, ledger.lock_subscription(db_session, t.sub.id), kind="adjustment",
                            bucket="top_up", amount=1, key="adjust:no-reason")
    db_session.rollback()
    with pytest.raises(ledger.InsufficientCredits):
        ledger.append_entry(db_session, ledger.lock_subscription(db_session, t.sub.id), kind="adjustment",
                            bucket="monthly", amount=-4, key="adjust:too-much", reason="test")
    db_session.rollback()


def test_billing_reads_are_organisation_scoped_and_open_to_viewers(client, db_session, enforced):
    a = _tenant(db_session, "billing-scope-a", credits=4)
    viewer = _tenant(db_session, "billing-scope-b", credits=7, role=MembershipRole.VIEWER)
    assert client.post("/api/v1/analyses", headers=a.headers, json=_payload(a)).status_code == 202
    seen = client.get("/api/v1/billing/summary", headers=viewer.headers)
    assert seen.status_code == 200
    assert [s["id"] for s in seen.json()["subscriptions"]] == [str(viewer.sub.id)]
    assert all(row["task_id"] is None for row in client.get("/api/v1/billing/ledger", headers=viewer.headers).json()["items"])
    assert client.post("/api/v1/analyses", headers=viewer.headers, json=_payload(viewer)).status_code == 403
    assert client.get("/api/v1/billing/summary").status_code == 403  # service context has no organisation
