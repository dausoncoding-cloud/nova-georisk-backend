"""Plan 4.1 / 4.4 / 4.6 at the API: preflight endpoint and server-side enforcement on submit (the 4 'no imagery' cases)."""
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from geoalchemy2.elements import WKTElement

from app.core.config import get_settings
from app.core.rate_limit import FixedWindowRateLimiter, get_preflight_limiter
from app.main import app
from app.models.aoi import AOI
from app.models.task import Task
from app.services.firris import preflight
from app.workers.celery_tasks import run_engine_analysis
from tests.integration.test_firris_execution import _tenant

RUFIJI_WKT = "MULTIPOLYGON(((38.92 -7.99,39.01 -7.99,39.01 -7.9,38.92 -7.9,38.92 -7.99)))"


def _period(dates=(), orbits=(), s2=1, before=None, after=None):
    return {"sentinel1_pass_dates": [date.fromisoformat(d) for d in dates], "relative_orbits": list(orbits),
            "sentinel2_compliant_scenes": s2, "nearest_pass_before": before and date.fromisoformat(before),
            "nearest_pass_after": after and date.fromisoformat(after)}


OK = {"target": _period(["2024-05-25"], [57]), "baseline": _period(["2022-08-28"], [57], s2=2)}


@pytest.fixture
def setup(client, db_session, monkeypatch):
    from app.models.project import Project
    organization, headers = _tenant(db_session, f"preflight-{uuid.uuid4().hex[:8]}")
    project = Project(name="Rufiji", organization_id=organization.id, engine_key="firris", analysis_module="FIRRIS")
    db_session.add(project)
    db_session.flush()

    def aoi(wkt=RUFIJI_WKT):
        item = AOI(project_id=project.id, name="Rufiji", source_type="drawn_polygon", geometry=WKTElement(wkt, srid=4326),
                   area_m2=1.0, area_hectares=0.0001, area_km2=0.000001, perimeter_m=4.0)
        db_session.add(item)
        db_session.flush()
        return item
    rufiji = aoi()
    db_session.commit()
    monkeypatch.setattr(run_engine_analysis, "delay", lambda task_id: SimpleNamespace(id="celery-preflight-test"))
    monkeypatch.setattr(preflight, "_today", lambda: date(2026, 11, 14))
    counts: dict[str, int] = {}

    def increment(key, ttl):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]
    app.dependency_overrides[get_preflight_limiter] = lambda: FixedWindowRateLimiter(increment)
    yield SimpleNamespace(project=project, aoi=rufiji, headers=headers, make_aoi=aoi, db=db_session)
    app.dependency_overrides.pop(get_preflight_limiter, None)


def _availability(monkeypatch, result):
    monkeypatch.setattr(preflight, "scene_availability", lambda *_args: result)


def _payload(project, aoi, target, baseline):
    return {
        "project_id": str(project.id), "aoi_id": str(aoi.id), "operation": "flood_mapping",
        "products": ["flood_extent", "flood_probability"],
        "parameters": {"workflow": {"source": {"provider": "gee", "target_period": {"start": target[0], "end": target[1]},
                                               "baseline_period": {"start": baseline[0], "end": baseline[1]}}}},
        "gis_metadata": {"crs": "EPSG:4326", "bounding_box": {"west": 38.92, "south": -7.99, "east": 39.01, "north": -7.9},
                         "spatial_resolution": {"x": 30, "y": 30, "unit": "m"}},
    }


CASES = {
    "before_2014": (("2014-06-01", "2014-06-10"), ("2013-06-01", "2013-06-10"), "3 October 2014"),
    "no_s1_pass": (("2024-05-21", "2024-05-23"), ("2022-08-28", "2022-09-03"), "No Sentinel-1 pass"),
    "future": (("2027-01-01", "2027-01-05"), ("2026-01-01", "2026-01-05"), "after today"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_no_imagery_cases_are_refused_at_submit_with_a_clear_message(client, setup, monkeypatch, case):
    target, baseline, phrase = CASES[case]
    _availability(monkeypatch, {"target": _period(before="2024-05-13", after="2024-05-25"), "baseline": OK["baseline"]}
                  if case == "no_s1_pass" else OK)
    before = setup.db.query(Task).count()
    response = client.post("/api/v1/analyses", headers=setup.headers, json=_payload(setup.project, setup.aoi, target, baseline))
    assert response.status_code == 422, response.text
    assert phrase in response.json()["detail"]
    assert "Traceback" not in response.text and "ee." not in response.json()["detail"]
    if case == "no_s1_pass":
        # P6: inclusive wording; the API window 2024-05-21 → 2024-05-23 (exclusive) covers 21 and 22 May.
        assert response.json()["detail"] == ("No Sentinel-1 pass over this area between 21 and 22 May 2024. "
                                             "Nearest usable passes: before 13 May 2024, after 25 May 2024.")
    assert setup.db.query(Task).count() == before


def test_sentinel1_without_compliant_sentinel2_is_accepted_with_a_warning(client, setup, monkeypatch):
    _availability(monkeypatch, {"target": _period(["2024-04-19"], [57], s2=0), "baseline": OK["baseline"]})
    payload = _payload(setup.project, setup.aoi, ("2024-04-18", "2024-04-20"), ("2022-08-28", "2022-09-03"))
    checked = client.post("/api/v1/analyses/preflight", headers=setup.headers, json=payload)
    assert checked.status_code == 200 and checked.json()["ok"] is True
    assert [w["code"] for w in checked.json()["warnings"]] == ["no_compliant_sentinel2"]
    submitted = client.post("/api/v1/analyses", headers=setup.headers, json=payload)
    assert submitted.status_code == 202, submitted.text
    assert [w["code"] for w in submitted.json()["preflight_warnings"]] == ["no_compliant_sentinel2"]


def test_preflight_reports_passes_orbits_capacity_and_never_creates_a_task(client, setup, monkeypatch):
    _availability(monkeypatch, OK)
    before = setup.db.query(Task).count()
    response = client.post("/api/v1/analyses/preflight", headers=setup.headers,
                           json=_payload(setup.project, setup.aoi, ("2024-05-24", "2024-05-26"), ("2022-08-28", "2022-09-03")))
    body = response.json()
    assert response.status_code == 200 and body["ok"] is True and body["blocking"] == []
    assert body["target"]["sentinel1_pass_dates"] == ["2024-05-25"] and body["shared_relative_orbits"] == [57]
    assert body["capacity"]["bbox_pixels"] == 112225 and body["capacity"]["limit_bytes"] == 50331648
    assert setup.db.query(Task).count() == before


@pytest.mark.parametrize("baseline, status", [(("2014-10-03", "2014-10-05"), 200), (("2014-10-02", "2014-10-05"), 422)])
def test_boundary_dates_at_submit(client, setup, monkeypatch, baseline, status):
    _availability(monkeypatch, OK)
    response = client.post("/api/v1/analyses", headers=setup.headers,
                           json=_payload(setup.project, setup.aoi, ("2024-05-24", "2024-05-26"), baseline))
    assert response.status_code == (202 if status == 200 else 422), response.text


def test_oversize_area_is_refused_with_split_advice(client, setup, monkeypatch):
    calls = []
    monkeypatch.setattr(preflight, "scene_availability", lambda *args: calls.append(args) or OK)
    big = setup.make_aoi("MULTIPOLYGON(((36 -7,37 -7,37 -6,36 -6,36 -7)))")
    setup.db.commit()
    payload = _payload(setup.project, big, ("2024-05-24", "2024-05-26"), ("2022-08-28", "2022-09-03"))
    response = client.post("/api/v1/analyses", headers=setup.headers, json=payload)
    assert response.status_code == 422 and "smaller area" in response.json()["detail"] and "split" in response.json()["detail"]
    checked = client.post("/api/v1/analyses/preflight", headers=setup.headers, json=payload).json()
    assert [b["code"] for b in checked["blocking"]] == ["capacity_exceeded"] and checked["capacity"]["ratio"] > 1 and calls == []


def test_preflight_is_rate_limited_per_user(client, setup, monkeypatch):
    _availability(monkeypatch, OK)
    monkeypatch.setattr(get_settings(), "firris_preflight_per_user_per_minute", 2)
    payload = _payload(setup.project, setup.aoi, ("2024-05-24", "2024-05-26"), ("2022-08-28", "2022-09-03"))
    statuses = [client.post("/api/v1/analyses/preflight", headers=setup.headers, json=payload).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    limited = client.post("/api/v1/analyses/preflight", headers=setup.headers, json=payload)
    assert limited.headers.get("Retry-After") == "60" and "wait a minute" in limited.json()["detail"]


def test_preflight_requires_identity_and_is_organization_scoped(client, setup, db_session, monkeypatch):
    _availability(monkeypatch, OK)
    payload = _payload(setup.project, setup.aoi, ("2024-05-24", "2024-05-26"), ("2022-08-28", "2022-09-03"))
    # Without a valid internal secret the API refuses (browsers reach it only through the BFF session; see
    # tests/unit/test_phase0_security.py::test_bff_refuses_anonymous_preflight_before_reaching_the_api).
    assert client.post("/api/v1/analyses/preflight", headers={"X-Internal-Secret": "wrong"}, json=payload).status_code == 401
    _, other_headers = _tenant(db_session, f"preflight-other-{uuid.uuid4().hex[:8]}")
    db_session.commit()
    assert client.post("/api/v1/analyses/preflight", headers=other_headers, json=payload).status_code in (403, 404)


def test_provider_failure_returns_a_plain_503(client, setup, monkeypatch):
    def fail(*_args):
        raise RuntimeError("ee.ee_exception.EEException: quota detail for project secret-project")
    monkeypatch.setattr(preflight, "scene_availability", fail)
    payload = _payload(setup.project, setup.aoi, ("2024-05-24", "2024-05-26"), ("2022-08-28", "2022-09-03"))
    for path in ("/api/v1/analyses/preflight", "/api/v1/analyses"):
        response = client.post(path, headers=setup.headers, json=payload)
        assert response.status_code == 503 and response.json()["detail"] == preflight.UNAVAILABLE_MESSAGE
        assert "secret-project" not in response.text and "EEException" not in response.text
