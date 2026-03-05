"""Shared pytest fixtures for tech-assessment-hub tests."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from src.models import Instance
from src import models_sn  # noqa: F401 - ensure SN mirror relationships are registered
from src.database import get_session


@pytest.fixture()
def db_engine():
    """Create a fresh in-memory SQLite engine with all tables.

    Uses StaticPool so that every connection shares the same underlying
    in-memory database.  Without this, SQLite ':memory:' would create a
    separate empty database per connection, causing "no such table" errors
    whenever a Session commits and then queries again.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    """Provide a SQLModel Session that rolls back after each test."""
    session = Session(db_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def client(db_session):
    """Provide a FastAPI TestClient wired to the in-memory test database.

    Temporarily removes startup/shutdown event handlers so the app does not
    try to hit the real SQLite database (which may be locked or absent in CI).
    Tables are already created by the db_engine fixture.
    """
    from src.server import app

    def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session

    # Stash and clear lifecycle event handlers to avoid real-DB side effects.
    saved_startup = app.router.on_startup[:]
    saved_shutdown = app.router.on_shutdown[:]
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    try:
        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc
    finally:
        app.dependency_overrides.clear()
        app.router.on_startup = saved_startup
        app.router.on_shutdown = saved_shutdown


@pytest.fixture()
def sample_instance(db_session):
    """Insert and return a minimal Instance row for tests that need one."""
    instance = Instance(
        name="test",
        url="https://example.service-now.com",
        username="admin",
        password_encrypted="not-a-real-secret",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)
    return instance
