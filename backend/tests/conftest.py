import pytest

from app.persistence.memory import InMemoryStore


@pytest.fixture(scope="session")
def postgres_url():
    """One throwaway Postgres 18 container per test session. Only
    requested by integration tests, so `pytest -m "not integration"` never
    starts Docker."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:18-alpine", driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(params=["memory"])
def store(request):
    """Every Store contract test runs once per implementation. Task 7 adds
    the "postgres" param."""
    return InMemoryStore()
