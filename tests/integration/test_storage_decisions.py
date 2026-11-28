"""Q5 (decided 2026-11-21): warnings at 90% and 100%; at 100% new analyses stop until space is freed or added;
viewing and downloads always allowed. (a) Free up space: delete a result's files after confirming (owners and
admins, audited). (b) Request extra storage from NOVA ARI."""
import uuid

import pytest

from app.core.config import get_settings
from app.models.billing import PlatformAudit
from app.models.identity import MembershipRole
from app.models.result import Result
from app.models.task import Task
from app.services.billing import limits
from tests.integration.test_billing_accounts import _submit
from tests.integration.test_billing_credits import _queue, _tenant  # noqa: F401 (_queue: no Celery)

GB = 1_000_000_000


@pytest.fixture(autouse=True, params=[False, True], ids=["enforcement-off", "enforcement-on"])
def enforcement(request, monkeypatch):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", request.param)
    return request.param


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    return tmp_path


def _result(db, t, root, name, size, version=1):
    task_id = db.query(Task.id).filter(Task.project_id == t.project.id).limit(1).scalar()
    (root / f"{name}.tif").write_bytes(b"x" * 10)
    (root / f"{name}.pdf").write_bytes(b"y" * 10)
    result = Result(task_id=task_id, project_id=t.project.id, aoi_id=t.aoi.id, result_type="flood_extent_map",
                    version=version, output_files={
                        "map": {"path": f"{name}.tif", "file_size_bytes": size, "label": "Flood map"},
                        "report": {"path": f"{name}.pdf", "file_size_bytes": size // 10, "label": "Report"}})
    db.add(result)
    db.commit()
    return result


def test_free_up_space_deletes_files_only_after_confirming_and_unblocks(client, db_session, root, enforcement, monkeypatch):
    t = _tenant(db_session, "st-free", credits=5)
    assert _submit(client, t).status_code == 202  # a task to hang results on
    big = _result(db_session, t, root, "big", int(1.7 * GB))
    _result(db_session, t, root, "small", int(0.2 * GB), version=2)
    overview = client.get("/api/v1/billing/storage", headers=t.headers).json()
    assert (overview["level"], overview["blocks_at_limit"], overview["warning_levels"]) == (100, True, [90, 100])
    assert [item["result_id"] for item in overview["items"]][0] == str(big.id) and overview["can_manage"] is True
    item = overview["items"][0]
    assert item["downloads"] == [f"/api/v1/results/{big.id}/products/map", f"/api/v1/results/{big.id}/products/report"]
    # At 100%: new analyses stop (with enforcement on); viewing and downloads still work.
    blocked = _submit(client, t)
    if enforcement:
        assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "storage_full"
    else:
        assert blocked.status_code == 202  # enforcement off: today's behaviour
    assert client.get(f"/api/v1/results/{big.id}", headers=t.headers).status_code == 200
    assert client.get(item["downloads"][0], headers=t.headers).status_code == 200
    path = f"/api/v1/billing/storage/results/{big.id}/delete-files"
    wrong = client.post(path, headers=t.headers, json={"confirm": "nope"})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "confirmation_mismatch"
    assert (root / "big.tif").exists()
    done = client.post(path, headers=t.headers, json={"confirm": item["confirmation_code"]})
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["files_deleted"], body["bytes_freed"]) == (2, int(1.7 * GB) + int(0.17 * GB))
    assert not (root / "big.tif").exists() and not (root / "big.pdf").exists() and (root / "small.tif").exists()
    assert body["storage"]["level"] is None and limits.storage_used(db_session, t.org.id) < 0.9 * 2 * GB
    # The result and its history stay; the files are gone from it.
    view = client.get(f"/api/v1/results/{big.id}", headers=t.headers)
    assert view.status_code == 200 and view.json()["products"] == []
    assert client.get(item["downloads"][0], headers=t.headers).status_code == 404
    assert client.post(path, headers=t.headers, json={"confirm": item["confirmation_code"]}).status_code == 409
    event = db_session.query(PlatformAudit).filter_by(action="storage.files_deleted", target_id=str(big.id)).one()
    assert event.actor_user_id == t.user.id and event.organization_id == t.org.id
    assert event.current["bytes_freed"] == body["bytes_freed"]
    assert _submit(client, t).status_code == 202  # space freed: analyses run again


def test_only_owners_and_admins_of_the_organisation_delete(client, db_session, root):
    t = _tenant(db_session, "st-roles", credits=5)
    _submit(client, t)
    result = _result(db_session, t, root, "kept", GB // 10)
    viewer = _tenant(db_session, "st-roles-viewer", role=MembershipRole.VIEWER)
    other = _tenant(db_session, "st-roles-other")
    code = str(result.id)[:8]
    path = f"/api/v1/billing/storage/results/{result.id}/delete-files"
    assert client.post(path, headers=viewer.headers, json={"confirm": code}).status_code == 403
    assert client.post(path, headers=other.headers, json={"confirm": code}).status_code == 404
    assert client.post(f"/api/v1/billing/storage/results/{uuid.uuid4()}/delete-files", headers=t.headers,
                       json={"confirm": code}).status_code == 404
    assert (root / "kept.tif").exists()
    assert client.get("/api/v1/billing/storage", headers=other.headers).json()["items"] == []


def test_a_path_outside_the_artifact_root_is_never_deleted(client, db_session, root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("keep")
    t = _tenant(db_session, "st-escape", credits=5)
    _submit(client, t)
    result = _result(db_session, t, root, "escape", GB // 10)
    result.output_files = {**result.output_files, "evil": {"path": str(outside), "file_size_bytes": 1}}
    db_session.commit()
    response = client.post(f"/api/v1/billing/storage/results/{result.id}/delete-files", headers=t.headers,
                           json={"confirm": str(result.id)[:8]})
    assert response.status_code == 200 and outside.read_text() == "keep"
    assert response.json()["files_deleted"] == 2


def test_request_extra_storage_goes_to_nova_ari(client, db_session):
    t = _tenant(db_session, "st-request")
    response = client.post("/api/v1/billing/requests", headers=t.headers,
                           json={"subscription_id": str(t.sub.id), "kind": "storage", "storage_gb": 5})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["storage_gb"], body["storage_price"], body["status"]) == ("storage", 5, None, "open")
    again = client.post("/api/v1/billing/requests", headers=t.headers,
                        json={"subscription_id": str(t.sub.id), "kind": "storage", "storage_gb": 5}).json()
    assert again["existing"] is True and again["id"] == body["id"]
    assert client.post("/api/v1/billing/requests", headers=t.headers,
                       json={"subscription_id": str(t.sub.id), "kind": "storage"}).status_code == 422


def test_free_up_space_keeps_the_execution_archive(client, db_session, root):
    """Owner decision 2026-11-28: the execution archive (audit/export copy) is never deleted; every other output
    file is; the result record, summary, provenance and GET /tasks/{id}/archive stay."""
    from app.workers.celery_tasks import execute_engine_task
    t = _tenant(db_session, "st-archive", credits=5)
    submitted = _submit(client, t)
    assert submitted.status_code == 202, submitted.text
    task_id = uuid.UUID(submitted.json()["task"]["id"])
    execute_engine_task(db_session, task_id)
    db_session.expire_all()
    result = db_session.query(Result).filter(Result.task_id == task_id).one()
    files = {key: entry for key, entry in result.output_files.items() if entry.get("path")}
    assert "execution_archive" in files and len(files) >= 2, sorted(files)
    archive = root / files["execution_archive"]["path"]
    others = [root / entry["path"] for key, entry in files.items() if key != "execution_archive"]
    assert archive.name == "execution-archive.json" and archive.is_file() and all(p.is_file() for p in others)
    archive_bytes = archive.read_bytes()
    summary, provenance = result.summary, result.provenance
    assert summary and provenance
    before = client.get(f"/api/v1/tasks/{task_id}/archive", headers=t.headers)
    assert before.status_code == 200, before.text

    item = next(i for i in client.get("/api/v1/billing/storage", headers=t.headers).json()["items"]
                if i["result_id"] == str(result.id))
    assert item["files"] == len(others)
    assert item["bytes"] == sum(e.get("file_size_bytes") or 0 for k, e in files.items() if k != "execution_archive")
    assert f"/api/v1/results/{result.id}/products/execution_archive" not in item["downloads"]
    done = client.post(f"/api/v1/billing/storage/results/{result.id}/delete-files", headers=t.headers,
                       json={"confirm": item["confirmation_code"]})
    assert done.status_code == 200, done.text
    assert done.json()["files_deleted"] == len(others)

    # The archive file remains, unchanged; every other output file is gone.
    assert archive.is_file() and archive.read_bytes() == archive_bytes
    assert not any(p.exists() for p in others)
    db_session.expire_all()
    kept = db_session.get(Result, result.id)
    assert kept.output_files["execution_archive"] == files["execution_archive"]
    assert all("deleted_at" in kept.output_files[k] and "path" not in kept.output_files[k]
               for k in files if k != "execution_archive")
    # The result record, summary and provenance remain.
    assert (kept.summary, kept.provenance) == (summary, provenance)
    assert client.get(f"/api/v1/results/{result.id}", headers=t.headers).status_code == 200
    # The archive is still downloadable, and GET /tasks/{id}/archive still works with the same record.
    assert client.get(f"/api/v1/results/{result.id}/products/execution_archive", headers=t.headers).status_code == 200
    after = client.get(f"/api/v1/tasks/{task_id}/archive", headers=t.headers)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
    assert [r["id"] for r in after.json()["results"]] == [str(result.id)]
    # Nothing left to free: the result leaves the list, and a second delete is refused.
    listed = client.get("/api/v1/billing/storage", headers=t.headers).json()["items"]
    assert str(result.id) not in [i["result_id"] for i in listed]
    again = client.post(f"/api/v1/billing/storage/results/{result.id}/delete-files", headers=t.headers,
                        json={"confirm": item["confirmation_code"]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "files_already_deleted"
    event = db_session.query(PlatformAudit).filter_by(action="storage.files_deleted", target_id=str(result.id)).one()
    assert "execution_archive" not in event.previous["files"] and "execution_archive" not in event.current["deleted"]
