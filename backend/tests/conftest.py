import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.persistence.memory import InMemoryStore


@pytest.fixture(scope="session")
def postgres_url():
    """One throwaway Postgres 18 container per test session. Only
    requested by integration tests, so `pytest -m "not integration"` never
    starts Docker."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:18-alpine", driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture
def fresh_database_url(postgres_url):
    """A brand-new empty database on the session container, dropped after
    the test - for tests that must start from (or return to) an empty
    schema without disturbing the shared test database."""
    name = f"t_{uuid.uuid4().hex}"
    admin = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(params=["memory"])
def store(request):
    """Every Store contract test runs once per implementation. Task 7 adds
    the "postgres" param."""
    return InMemoryStore()
