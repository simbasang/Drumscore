from fastapi.testclient import TestClient

from app.main import app, get_readiness_checks
from app.readiness import CheckResult

client = TestClient(app)


def test_health_returns_ok_status():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def ready_with(results):
    app.dependency_overrides[get_readiness_checks] = lambda: results
    try:
        return client.get("/api/ready")
    finally:
        app.dependency_overrides.clear()


def test_ready_should_return_200_when_every_check_passes():
    response = ready_with([CheckResult("database", True, "ok"), CheckResult("storage", True, "writable")])

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": [
            {"name": "database", "ok": True, "detail": "ok"},
            {"name": "storage", "ok": True, "detail": "writable"},
        ],
    }


def test_ready_should_return_503_when_a_check_fails():
    response = ready_with([CheckResult("database", False, "OperationalError"), CheckResult("storage", True, "writable")])

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
