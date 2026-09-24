import pytest


@pytest.fixture(scope="session")
def postgres_url():
    """One throwaway Postgres 18 container per test session. Only
    requested by integration tests, so `pytest -m "not integration"` never
    starts Docker."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:18-alpine", driver="psycopg") as container:
        yield container.get_connection_url()
