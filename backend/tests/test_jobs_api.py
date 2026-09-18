import pytest
from fastapi.testclient import TestClient

from app.api.jobs import (
    get_audio_extractor,
    get_job_store,
    get_stem_separator,
    get_storage_dir,
    get_tempo_estimator,
    get_transcriber,
)
from app.audio_extraction import AudioExtractionError
from app.jobs import JobStore
from app.main import app
from app.stem_separation import SeparatedStems, StemSeparationError
from app.tempo_estimation import TempoEstimationError
from app.transcription import DrumEvent, DrumInstrument, TranscriptionError

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


class FakeTranscriber:
    def transcribe(self, audio_path):
        return [
            DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK),
            DrumEvent(id="e2", time=0.5, instrument=DrumInstrument.HIHAT_CLOSED),
        ]


class FailingTranscriber:
    def transcribe(self, audio_path):
        raise TranscriptionError("model crashed")


class FakeTempoEstimator:
    def estimate(self, audio_path):
        return 128.0


class FailingTempoEstimator:
    def estimate(self, audio_path):
        raise TempoEstimationError("could not estimate tempo")


@pytest.fixture(autouse=True)
def isolated_dependencies(tmp_path):
    store = JobStore()
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_audio_extractor] = lambda: FakeAudioExtractor()
    app.dependency_overrides[get_stem_separator] = lambda: FakeStemSeparator()
    app.dependency_overrides[get_transcriber] = lambda: FakeTranscriber()
    app.dependency_overrides[get_tempo_estimator] = lambda: FakeTempoEstimator()
    app.dependency_overrides[get_storage_dir] = lambda: tmp_path
    yield store
    app.dependency_overrides.pop(get_job_store, None)
    app.dependency_overrides.pop(get_audio_extractor, None)
    app.dependency_overrides.pop(get_stem_separator, None)
    app.dependency_overrides.pop(get_transcriber, None)
    app.dependency_overrides.pop(get_tempo_estimator, None)
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


def test_create_job_runs_pipeline_to_tempo_mapped():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["status"] == "tempo_mapped"
    assert body["audio_path"].endswith("source.wav")
    assert body["drums_path"].endswith("drums.wav")
    assert body["accompaniment_path"].endswith("no_drums.wav")
    assert body["event_count"] == 2
    assert body["tempo_bpm"] == 128.0


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


def test_create_job_reports_transcription_failure_as_job_error():
    app.dependency_overrides[get_transcriber] = lambda: FailingTranscriber()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "model crashed"


def test_create_job_reports_tempo_mapping_failure_as_job_error():
    app.dependency_overrides[get_tempo_estimator] = lambda: FailingTempoEstimator()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "could not estimate tempo"


def test_get_analysis_returns_tempo_and_events_when_job_is_tempo_mapped():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["tempo_bpm"] == 128.0
    assert len(body["events"]) == 2
    assert body["events"][0]["instrument"] == "kick"
    assert body["events"][0]["time"] == 0.5


def test_get_analysis_returns_409_when_job_not_yet_tempo_mapped():
    app.dependency_overrides[get_transcriber] = lambda: FailingTranscriber()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/analysis")

    assert response.status_code == 409


def test_get_analysis_returns_404_for_unknown_job():
    response = client.get("/api/jobs/does-not-exist/analysis")

    assert response.status_code == 404


def test_get_drums_audio_returns_file_when_available():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/audio/drums")

    assert response.status_code == 200
    assert response.content == b"fake drums"
    assert response.headers["content-type"] == "audio/wav"


def test_get_accompaniment_audio_returns_file_when_available():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/audio/accompaniment")

    assert response.status_code == 200
    assert response.content == b"fake accompaniment"
    assert response.headers["content-type"] == "audio/wav"


def test_get_drums_audio_returns_404_for_unknown_job():
    response = client.get("/api/jobs/does-not-exist/audio/drums")

    assert response.status_code == 404


def test_get_accompaniment_audio_returns_404_for_unknown_job():
    response = client.get("/api/jobs/does-not-exist/audio/accompaniment")

    assert response.status_code == 404


def test_get_drums_audio_returns_409_when_not_ready_yet():
    app.dependency_overrides[get_audio_extractor] = lambda: FailingAudioExtractor()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/audio/drums")

    assert response.status_code == 409


def test_get_job_returns_previously_created_job():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_job_returns_404_for_unknown_id():
    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
