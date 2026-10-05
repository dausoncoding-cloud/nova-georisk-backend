"""Assert Phase 0/0.5 schema and legacy backfills on a disposable test database."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from scripts.seed_pre_phase0_fixture import AOI_ID, PROJECT_ID, RESULT_ID, TASK_ID


def main() -> None:
    url = get_settings().database_url
    database = make_url(url).database or ""
    if "test" not in database.lower():
        raise SystemExit("Refusing schema verification against a non-test database.")
    engine = create_engine(url)
    inspector = inspect(engine)
    required_tables = {
        "organizations",
        "users",
        "organization_memberships",
        "organization_invitations",
        "engines",
        "billing_plans",
        "billing_plan_engines",
        "organization_subscriptions",
        "organization_engine_entitlements",
        "projects",
        "aois",
        "tasks",
        "results",
    }
    missing = required_tables - set(inspector.get_table_names())
    assert not missing, f"Missing tables: {sorted(missing)}"

    project_columns = {column["name"]: column for column in inspector.get_columns("projects")}
    assert project_columns["organization_id"]["nullable"] is False
    assert project_columns["engine_key"]["nullable"] is False
    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    assert {"aoi_id", "engine_key", "started_at", "completed_at", "error_summary"} <= task_columns
    result_columns = {column["name"] for column in inspector.get_columns("results")}
    assert {"project_id", "aoi_id", "engine_key", "version", "provenance"} <= result_columns
    result_column_details = {
        column["name"]: column for column in inspector.get_columns("results")
    }
    assert result_column_details["project_id"]["nullable"] is False
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("users")} >= {
        "uq_users_issuer_subject"
    }
    assert {
        constraint["name"] for constraint in inspector.get_unique_constraints("results")
    } >= {"uq_result_version"}
    assert inspector.get_pk_constraint("organization_memberships")["constrained_columns"] == [
        "organization_id",
        "user_id",
    ]
    assert {index["name"] for index in inspector.get_indexes("tasks")} >= {
        "ix_tasks_project_id",
        "ix_tasks_aoi_id",
        "ix_tasks_status",
    }

    with engine.connect() as connection:
        project_org, project_engine = connection.execute(
            text("SELECT organization_id, engine_key FROM projects WHERE id=:id"),
            {"id": PROJECT_ID},
        ).one()
        task = connection.execute(
            text("SELECT aoi_id, engine_key, started_at, completed_at FROM tasks WHERE id=:id"),
            {"id": TASK_ID},
        ).one()
        result_project, result_aoi, result_engine = connection.execute(
            text("SELECT project_id, aoi_id, engine_key FROM results WHERE id=:id"),
            {"id": RESULT_ID},
        ).one()
        assert str(project_org) == "00000000-0000-0000-0000-000000000001"
        assert project_engine == "firris"
        assert str(task.aoi_id) == AOI_ID
        assert task.engine_key == "firris"
        assert task.started_at is not None and task.completed_at is not None
        assert str(result_project) == PROJECT_ID
        assert str(result_aoi) == AOI_ID
        assert result_engine == "firris"
        assert connection.execute(text("SELECT count(*) FROM engines")).scalar_one() == 10
        assert connection.execute(
            text(
                "SELECT count(*) FROM organization_engine_entitlements "
                "WHERE organization_id=:organization_id AND engine_key='firris' AND status='ACTIVE'"
            ),
            {"organization_id": project_org},
        ).scalar_one() == 1

    # Imports exercise settings, routes, model relationships, and application startup.
    from app.main import app  # noqa: F401

    print("Phase 0.5 schema, constraints, backfills, and app startup verified.")


if __name__ == "__main__":
    main()
