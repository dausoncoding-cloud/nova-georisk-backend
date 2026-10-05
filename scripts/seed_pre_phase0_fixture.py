"""Seed a deterministic pre-Phase-0 fixture into a disposable test database only."""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


PROJECT_ID = "10000000-0000-4000-8000-000000000001"
AOI_ID = "20000000-0000-4000-8000-000000000001"
TASK_ID = "30000000-0000-4000-8000-000000000001"
RESULT_ID = "40000000-0000-4000-8000-000000000001"


def main() -> None:
    url = get_settings().database_url
    database = make_url(url).database or ""
    if "test" not in database.lower():
        raise SystemExit("Refusing to seed a database whose name does not contain 'test'.")
    engine = create_engine(url)
    with engine.begin() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != "eb3a25ef583f":
            raise SystemExit("Pre-Phase-0 fixture requires migration revision eb3a25ef583f.")
        connection.execute(
            text(
                """
                INSERT INTO projects
                    (id, name, description, crs, analysis_module, created_at, updated_at)
                VALUES
                    (:project_id, 'Legacy migration fixture', NULL, 'EPSG:4326', 'FIRAS', now(), now());
                INSERT INTO aois
                    (id, project_id, name, source_type, geometry, area_m2, area_hectares,
                     area_km2, perimeter_m, created_at, updated_at)
                VALUES
                    (:aoi_id, :project_id, 'Legacy AOI', 'drawn_polygon',
                     ST_Multi(ST_GeomFromText('POLYGON((36 -2,37 -2,37 -1,36 -1,36 -2))', 4326)),
                     1, 1, 1, 1, now(), now());
                INSERT INTO tasks
                    (id, project_id, task_type, status, progress_pct, input_params,
                     created_at, updated_at)
                VALUES
                    (:task_id, :project_id, 'INGESTION', 'COMPLETED', 100,
                     jsonb_build_object('aoi_id', :aoi_id), now() - interval '1 minute', now());
                INSERT INTO results
                    (id, task_id, result_type, summary, output_files, created_at, updated_at)
                VALUES
                    (:result_id, :task_id, 'screening_atlas', '{}'::jsonb, '{}'::jsonb, now(), now());
                """
            ),
            {
                "project_id": PROJECT_ID,
                "aoi_id": AOI_ID,
                "task_id": TASK_ID,
                "result_id": RESULT_ID,
            },
        )
    print("Seeded deterministic pre-Phase-0 migration fixture.")


if __name__ == "__main__":
    main()
