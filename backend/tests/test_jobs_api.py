import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.jobs import (
    BeatPointResponse,
    TempoMapResponse,
    TempoPointResponse,
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
from app.timing import BeatPoint, TempoMap, TempoPoint
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


def _create_job_through_to_tempo_mapped() -> str:
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    return create_response.json()["id"]


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


def test_get_job_exposes_tempo_map_alongside_the_legacy_scalar_bpm():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    body = response.json()
    assert body["tempo_bpm"] == 128.0
    assert body["tempo_map"] == {"points": [{"source_time": 0.0, "bpm": 128.0}]}


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


def test_get_diagnostics_returns_traced_events_when_job_is_tempo_mapped():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["tempo_bpm"] == 128.0
    assert len(body["events"]) == 2
    assert body["events"][0]["event_id"] == "e1"
    assert body["events"][0]["source_time"] == 0.5
    assert body["events"][0]["measure"] is not None
    assert isinstance(body["events"][0]["quantization_error_seconds"], float)


def test_get_diagnostics_returns_409_when_job_not_yet_tempo_mapped():
    app.dependency_overrides[get_transcriber] = lambda: FailingTranscriber()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/diagnostics")

    assert response.status_code == 409


def test_get_diagnostics_returns_404_for_unknown_job():
    response = client.get("/api/jobs/does-not-exist/diagnostics")

    assert response.status_code == 404


def test_get_diagnostics_does_not_change_job_state_or_analysis_output():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]
    analysis_before = client.get(f"/api/jobs/{job_id}/analysis").json()
    job_before = client.get(f"/api/jobs/{job_id}").json()

    client.get(f"/api/jobs/{job_id}/diagnostics")

    analysis_after = client.get(f"/api/jobs/{job_id}/analysis").json()
    job_after = client.get(f"/api/jobs/{job_id}").json()
    assert analysis_after == analysis_before
    assert job_after == job_before


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


def test_get_job_drums_audio_logs_warning_when_job_not_found(caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.jobs"):
        response = client.get("/api/jobs/does-not-exist/audio/drums")

    assert response.status_code == 404
    assert any(
        record.name == "app.api.jobs"
        and record.levelno == logging.WARNING
        and "does-not-exist" in record.getMessage()
        for record in caplog.records
    )


def test_get_job_drums_audio_logs_warning_when_not_ready(caplog):
    app.dependency_overrides[get_audio_extractor] = lambda: FailingAudioExtractor()

    job = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=abc12345678"}).json()
    job_id = job["id"]

    with caplog.at_level(logging.WARNING, logger="app.api.jobs"):
        response = client.get(f"/api/jobs/{job_id}/audio/drums")

    assert response.status_code == 409
    assert any(
        record.name == "app.api.jobs"
        and record.levelno == logging.WARNING
        and job_id in record.getMessage()
        for record in caplog.records
    )


def test_get_job_drums_audio_logs_info_on_success(caplog):
    job_id = _create_job_through_to_tempo_mapped()

    with caplog.at_level(logging.INFO, logger="app.api.jobs"):
        response = client.get(f"/api/jobs/{job_id}/audio/drums")

    assert response.status_code == 200
    assert any(
        record.name == "app.api.jobs"
        and record.levelno == logging.INFO
        and job_id in record.getMessage()
        for record in caplog.records
    )


def test_jobs_logger_is_configured_for_info_level():
    assert logging.getLogger("app.api.jobs").isEnabledFor(logging.INFO)


def test_retry_job_reruns_the_pipeline_from_the_failed_step():
    app.dependency_overrides[get_stem_separator] = lambda: FailingStemSeparator()
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"

    app.dependency_overrides[get_stem_separator] = lambda: FakeStemSeparator()
    retry_response = client.post(f"/api/jobs/{job_id}/retry")

    assert retry_response.status_code == 202
    final = client.get(f"/api/jobs/{job_id}").json()
    assert final["status"] == "tempo_mapped"
    assert final["error"] is None


def test_retry_job_returns_404_for_unknown_job():
    response = client.post("/api/jobs/does-not-exist/retry")

    assert response.status_code == 404


def test_retry_job_returns_409_when_job_has_not_failed():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.post(f"/api/jobs/{job_id}/retry")

    assert response.status_code == 409


def test_get_accompaniment_audio_returns_409_when_not_ready_yet():
    app.dependency_overrides[get_audio_extractor] = lambda: FailingAudioExtractor()

    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/audio/accompaniment")

    assert response.status_code == 409


def test_create_job_cleans_up_stale_jobs_and_their_files(isolated_dependencies):
    store = isolated_dependencies
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    old_job_id = create_response.json()["id"]
    store.update(
        old_job_id,
        created_at=datetime.now(UTC) - timedelta(hours=48),
    )

    client.post("/api/jobs", json={"url": "https://youtu.be/aaaaaaaaaaa"})

    assert client.get(f"/api/jobs/{old_job_id}").status_code == 404


def test_get_job_returns_previously_created_job():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_job_returns_404_for_unknown_id():
    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404


def test_get_job_logs_warning_when_job_not_found(caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.jobs"):
        response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
    assert any(
        record.name == "app.api.jobs"
        and record.levelno == logging.WARNING
        and "does-not-exist" in record.getMessage()
        for record in caplog.records
    )


def test_tempo_point_response_round_trips_a_domain_tempo_point():
    point = TempoPoint(source_time=1.5, bpm=120.0)

    response = TempoPointResponse.from_domain(point)
    dumped = response.model_dump()

    assert dumped == {"source_time": 1.5, "bpm": 120.0}


def test_beat_point_response_round_trips_a_domain_beat_point():
    point = BeatPoint(source_time=2.0, measure=1, beat=2, is_downbeat=False, confidence=0.9)

    response = BeatPointResponse.from_domain(point)
    dumped = response.model_dump()

    assert dumped == {
        "source_time": 2.0,
        "measure": 1,
        "beat": 2,
        "is_downbeat": False,
        "confidence": 0.9,
    }


def test_tempo_map_response_round_trips_a_domain_tempo_map():
    tempo_map = TempoMap.constant(128.0)

    response = TempoMapResponse.from_domain(tempo_map)
    dumped = response.model_dump()

    assert dumped == {"points": [{"source_time": 0.0, "bpm": 128.0}]}
