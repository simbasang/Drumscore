from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.config as app_config
from app.config import Settings
from app.persistence.migrations import downgrade_to_base, upgrade_to_head
from app.persistence.tables import metadata

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {"projects", "jobs", "artifacts", "analyses", "score_versions", "stage_cache"}

_BACKEND_DIR = Path(__file__).resolve().parent.parent


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


def test_cli_upgrade_without_sqlalchemy_url_falls_back_to_settings(monkeypatch, fresh_database_url):
    """The documented CLI workflow (`cd backend && uv run alembic upgrade
    head`) never sets sqlalchemy.url on the Config - alembic.ini has none -
    so migrations/env.py must fall back to get_settings().database_url with
    the secret unwrapped, not a SecretStr handed straight to create_engine."""
    monkeypatch.setattr(app_config, "get_settings", lambda: Settings(_env_file=None, database_url=fresh_database_url))
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))

    command.upgrade(config, "head")

    assert table_names(fresh_database_url) == EXPECTED_TABLES
