import pytest
from fastapi.testclient import TestClient

from app.api.jobs import get_audio_extractor, get_job_store, get_stem_separator, get_storage_dir
from app.audio_extraction import AudioExtractionError
from app.jobs import JobStore
from app.main import app
from app.stem_separation import SeparatedStems, StemSeparationError

client = TestClient(app)


class FakeAudioExtractor:
    def extract(self, source, destination_dir):
        destination_dir.mkdir(parents=True, exist_ok=True)
        path = destination_dir / "source.wav"
        path.write_bytes(b"fake wav data")
        return path


class FailingAudioExtractor:
    def extract(self, source, destination_dir):
        raise AudioExtractionError("video unavailable")


class FakeStemSeparator:
    def separate(self, audio_path, destination_dir):
        destination_dir.mkdir(parents=True, exist_ok=True)
        drums_path = destination_dir / "drums.wav"
        accompaniment_path = destination_dir / "no_drums.wav"
        drums_path.write_bytes(b"fake drums")
        accompaniment_path.write_bytes(b"fake accompaniment")
        return SeparatedStems(drums_path=drums_path, accompaniment_path=accompaniment_path)


class FailingStemSeparator:
    def separate(self, audio_path, destination_dir):
        raise StemSeparationError("out of memory")


@pytest.fixture(autouse=True)
def isolated_dependencies(tmp_path):
    store = JobStore()
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_audio_extractor] = lambda: FakeAudioExtractor()
    app.dependency_overrides[get_stem_separator] = lambda: FakeStemSeparator()
    app.dependency_overrides[get_storage_dir] = lambda: tmp_path
    yield store
    app.dependency_overrides.pop(get_job_store, None)
    app.dependency_overrides.pop(get_audio_extractor, None)
    app.dependency_overrides.pop(get_stem_separator, None)
    app.dependency_overrides.pop(get_storage_dir, None)


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


def test_create_job_runs_pipeline_to_stems_separated():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["status"] == "stems_separated"
    assert body["audio_path"].endswith("source.wav")
    assert body["drums_path"].endswith("drums.wav")
    assert body["accompaniment_path"].endswith("no_drums.wav")


def test_create_job_reports_extraction_failure_as_job_error():
    app.dependency_overrides[get_audio_extractor] = lambda: FailingAudioExtractor()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "video unavailable"


def test_create_job_reports_stem_separation_failure_as_job_error():
    app.dependency_overrides[get_stem_separator] = lambda: FailingStemSeparator()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "out of memory"


def test_get_job_returns_previously_created_job():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_job_returns_404_for_unknown_id():
    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
