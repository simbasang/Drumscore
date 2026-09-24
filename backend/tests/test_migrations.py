import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.persistence.migrations import downgrade_to_base, upgrade_to_head
from app.persistence.tables import metadata

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {"projects", "jobs", "artifacts", "analyses", "score_versions", "stage_cache"}


def table_names(url):
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_from_empty_creates_every_table(fresh_database_url):
    upgrade_to_head(fresh_database_url)

    assert table_names(fresh_database_url) == EXPECTED_TABLES


def test_migrated_schema_matches_sqlalchemy_metadata(fresh_database_url):
    upgrade_to_head(fresh_database_url)
    engine = create_engine(fresh_database_url)

    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), metadata)
    engine.dispose()

    assert diff == []


def test_downgrade_then_upgrade_round_trips(fresh_database_url):
    upgrade_to_head(fresh_database_url)

    downgrade_to_base(fresh_database_url)
    emptied = table_names(fresh_database_url)
    upgrade_to_head(fresh_database_url)

    assert emptied == set()
    assert table_names(fresh_database_url) == EXPECTED_TABLES
