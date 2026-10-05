"""
Shared fixtures for API integration tests.

Runs against a REAL PostgreSQL + PostGIS database (not SQLite/mocked)
since the AOI model's Geometry column needs actual PostGIS support —
SQLite can't stand in for that. `TEST_DATABASE_URL` points at a
disposable test database; each test gets a fresh schema via
`Base.metadata.create_all`/`drop_all` for isolation.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.platform import Engine
from app.platform.registry import ENGINE_DEFINITIONS

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is required for integration tests; use docker-compose.test.yml."
    )
test_database_name = make_url(TEST_DATABASE_URL).database or ""
if "test" not in test_database_name.lower():
    raise RuntimeError("TEST_DATABASE_URL must name a database containing 'test'.")
if TEST_DATABASE_URL == get_settings().database_url:
    raise RuntimeError("TEST_DATABASE_URL must not equal the application DATABASE_URL.")

INTERNAL_SECRET = "test-secret-for-integration-tests"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """Fresh schema per test — created before, dropped after."""
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    for definition in ENGINE_DEFINITIONS:
        if session.get(Engine, definition.key) is None:
            session.add(
                Engine(
                    key=definition.key,
                    name=definition.name,
                    description=definition.description,
                    status=definition.status,
                    enabled=definition.enabled,
                    version=definition.version,
                    category=definition.category,
                    route_namespace=definition.route_namespace,
                    icon_identifier=definition.icon_identifier,
                    capabilities={"features": list(definition.capabilities)},
                    publicly_available=definition.publicly_available,
                    subscription_required=definition.subscription_required,
                )
            )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session, monkeypatch):
    """FastAPI TestClient with the DB dependency overridden and a known internal secret."""
    settings = get_settings()
    monkeypatch.setattr(settings, "internal_api_secret", INTERNAL_SECRET)

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        test_client.headers.update({"X-Internal-Secret": INTERNAL_SECRET})
        yield test_client
    app.dependency_overrides.clear()
