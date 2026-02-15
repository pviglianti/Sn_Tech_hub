"""Shared pytest fixtures for tech-assessment-hub tests."""

import pytest
from sqlmodel import SQLModel, Session, create_engine

from src.models import Instance
from src import models_sn  # noqa: F401 - ensure SN mirror relationships are registered


@pytest.fixture()
def db_engine():
    """Create a fresh in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
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
