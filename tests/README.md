# Tests

## Unit tests (`tests/unit/`)

Pure logic — no database, no network, no external services. Every
statistics/hydrology/FIRAS/ML/validation/maps/reporting module is
covered here. Run with:

```bash
pytest tests/unit -v
```

## Integration tests (`tests/integration/`)

Exercise the actual FastAPI app + a real PostgreSQL/PostGIS database
end-to-end (project/AOI/task endpoints, auth, error responses). Not
mocked or run against SQLite, because the AOI model's `Geometry`
column requires real PostGIS support.

**Setup** (once):

```bash
# If you don't already have Postgres+PostGIS running (e.g. via the
# project's own docker-compose, or locally):
createdb nova_georisk_test
psql -d nova_georisk_test -c "CREATE EXTENSION postgis;"
```

**Run**:

```bash
export TEST_DATABASE_URL=postgresql+psycopg2://nova_user:nova_password@localhost:5432/nova_georisk_test
pytest tests/integration -v
```

Each test gets a fresh schema (`Base.metadata.create_all`/`drop_all`
per test via the `db_session` fixture in `conftest.py`) so tests are
isolated and order-independent.

## Coverage

```bash
pytest tests/ --cov=app --cov-report=term-missing
```

Currently ~90%. The gap is framework wiring that isn't meaningfully
testable without live infrastructure (Celery task execution needs a
running broker) or models not yet wired to an endpoint (`Dataset`,
`Result` — reserved for the GEE ingestion phase).
