from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware

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


def test_cors_middleware_allows_the_configured_origins():
    cors = next(entry for entry in main.app.user_middleware if entry.cls is CORSMiddleware)

    assert cors.kwargs["allow_origins"] == main._settings.cors_allowed_origins


def test_cors_preflight_echoes_an_allowed_origin_only(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None, run_migrations_on_startup=False))
    headers = {"Access-Control-Request-Method": "GET"}

    with TestClient(main.app) as client:
        allowed = client.options("/api/health", headers={**headers, "Origin": "http://localhost:3000"})
        refused = client.options("/api/health", headers={**headers, "Origin": "https://evil.example"})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in refused.headers
