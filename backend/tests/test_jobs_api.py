import pytest
from fastapi.testclient import TestClient

from app.api.jobs import get_job_store
from app.jobs import JobStore
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_job_store():
    store = JobStore()
    app.dependency_overrides[get_job_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_job_store, None)


def test_create_job_with_valid_url_returns_queued_job():
    response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "https://youtu.be/dQw4w9WgXcQ"
    assert body["status"] == "queued"
    assert body["id"]


def test_create_job_with_invalid_url_returns_422_with_detail():
    response = client.post("/api/jobs", json={"url": "https://vimeo.com/12345"})

    assert response.status_code == 422
    assert "not a supported YouTube URL" in response.json()["detail"]


def test_get_job_returns_previously_created_job():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_job_returns_404_for_unknown_id():
    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
