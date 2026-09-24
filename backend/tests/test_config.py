from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_settings_have_documented_defaults(monkeypatch):
    for name in ("DATABASE_URL", "STORAGE_ROOT", "WORKER_CONCURRENCY", "LEASE_SECONDS", "LOG_FORMAT", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
    assert settings.storage_root == Path(__file__).resolve().parent.parent / "data"
    assert settings.worker_concurrency == 2
    assert settings.lease_seconds == 300
    assert settings.heartbeat_seconds == 60
    assert settings.poll_interval_seconds == 2.0
    assert settings.max_attempts == 3
    assert settings.retry_base_seconds == 30
    assert settings.failed_job_retention_days == 7
    assert settings.prune_interval_seconds == 3600
    assert settings.storage_warn_bytes == 50 * 1024**3
    assert settings.run_migrations_on_startup is True
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.max_source_duration_seconds == 900
    assert settings.max_download_bytes == 200 * 1024**2
    assert settings.max_request_bytes == 5 * 1024**2
    assert settings.max_active_jobs == 20
    assert settings.storage_max_bytes == 100 * 1024**3


def test_settings_read_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKER_CONCURRENCY", "4")
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("MAX_ACTIVE_JOBS", "5")

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.storage_root == tmp_path
    assert settings.worker_concurrency == 4
    assert settings.log_format == "text"
    assert settings.max_active_jobs == 5


def test_database_password_is_hidden_from_repr():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:hunter2@db/x")

    text = repr(settings) + str(settings)

    assert "hunter2" not in text


@pytest.mark.parametrize(
    "field",
    ["max_source_duration_seconds", "max_download_bytes", "max_request_bytes", "max_active_jobs", "storage_max_bytes"],
)
def test_limits_must_be_positive(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_unknown_log_format_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_format="xml")


def test_storage_warning_must_not_exceed_the_storage_limit():
    with pytest.raises(ValidationError, match="STORAGE_WARN_BYTES must not exceed STORAGE_MAX_BYTES"):
        Settings(_env_file=None, storage_warn_bytes=11, storage_max_bytes=10)


def test_relative_storage_root_resolves_against_the_backend_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", "artifacts")

    settings = Settings(_env_file=None)

    assert settings.storage_root == BACKEND_DIR / "artifacts"


@pytest.mark.parametrize("heartbeat_seconds", [300, 301])
def test_heartbeat_must_be_shorter_than_the_lease(heartbeat_seconds):
    with pytest.raises(ValidationError, match="HEARTBEAT_SECONDS must be less than LEASE_SECONDS"):
        Settings(_env_file=None, lease_seconds=300, heartbeat_seconds=heartbeat_seconds)


def test_heartbeat_just_below_the_lease_is_accepted():
    settings = Settings(_env_file=None, lease_seconds=300, heartbeat_seconds=299.5)

    assert settings.heartbeat_seconds == 299.5
