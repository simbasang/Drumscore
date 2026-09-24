from pathlib import Path

from app.config import Settings


def test_settings_have_documented_defaults(monkeypatch):
    for name in ("DATABASE_URL", "STORAGE_ROOT", "WORKER_CONCURRENCY", "LEASE_SECONDS"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://drumscore:drumscore@localhost:5432/drumscore"
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


def test_settings_read_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKER_CONCURRENCY", "4")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"
    assert settings.storage_root == tmp_path
    assert settings.worker_concurrency == 4
