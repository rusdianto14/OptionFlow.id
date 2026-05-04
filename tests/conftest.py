"""Shared pytest fixtures.

We standardise on the local docker-compose Postgres for any test that touches
the DB. The fixture below resets the DB before each test that uses it.

If `DATABASE_URL_TEST` is set in env, that overrides the default. Otherwise the
fixture skips DB-dependent tests when the local DB is unreachable.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy
from sqlalchemy import text


def _default_test_db_url() -> str:
    return os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+psycopg://optionflow:optionflow@localhost:5432/optionflow",
    )


@pytest.fixture(scope="session")
def test_db_url() -> str:
    return _default_test_db_url()


@pytest.fixture(scope="session")
def _db_available(test_db_url: str) -> bool:
    """Probe the test DB. If unreachable, mark as unavailable so DB tests skip."""
    try:
        engine = sqlalchemy.create_engine(test_db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
def db_session(_db_available: bool, test_db_url: str, monkeypatch):
    """Provide a clean DB session: drops & recreates all tables before each test.

    Skips the test if Postgres is not reachable.
    """
    if not _db_available:
        pytest.skip(f"Postgres not reachable at {test_db_url}")

    monkeypatch.setenv("DATABASE_URL", test_db_url)
    # Force re-creation of cached engine/session
    from optionflow import db as db_mod

    db_mod._engine = None
    db_mod._SessionLocal = None

    db_mod.reset_db()
    factory = db_mod.get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
        db_mod.reset_db()  # leave clean for next test
        db_mod._engine = None
        db_mod._SessionLocal = None
