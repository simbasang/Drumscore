from fastapi.testclient import TestClient

from app import main
from app.config import Settings


def test_startup_runs_migrations_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None, database_url="postgresql+psycopg://x"))
    monkeypatch.setattr(main, "upgrade_to_head", calls.append)

    with TestClient(main.app):
        pass

    assert calls == ["postgresql+psycopg://x"]


def test_startup_skips_migrations_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None, run_migrations_on_startup=False))
    monkeypatch.setattr(main, "upgrade_to_head", calls.append)

    with TestClient(main.app):
        pass

    assert calls == []
