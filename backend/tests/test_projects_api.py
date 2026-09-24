import logging

import pytest
from fastapi.testclient import TestClient

from app.api.projects import get_app_settings, get_clock, get_source_validator, get_storage, get_store
from app.audio_extraction import AudioExtractionError
from app.config import Settings
from app.main import app
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind
from app.pipeline.runner import JobContext, process_job
from app.storage import LocalArtifactStorage
from app.youtube_source import YouTubeSourceValidator
from tests.fakes import FakeClock, FakeExtractor, logged_events, make_engines

URL = "https://youtu.be/dQw4w9WgXcQ"
OTHER_URL = "https://youtu.be/aaaaaaaaaaa"
MISSING = "00000000-0000-0000-0000-000000000000"


def override(store, storage, clock, settings=None):
    app.dependency_overrides.update({
        get_store: lambda: store,
        get_storage: lambda: storage,
        get_source_validator: YouTubeSourceValidator,
        get_clock: lambda: clock,
        get_app_settings: lambda: settings or Settings(_env_file=None),
    })


class Harness:
    def __init__(self, store, storage, clock):
        self.store, self.storage, self.clock = store, storage, clock
        self.client = TestClient(app)

    def process_next(self, engines=None):
        job = self.store.claim_next_job("w", 300, self.clock())
        process_job(job, JobContext(self.store, self.storage, engines or make_engines(), "w", 30, self.clock))
        return self.store.get_job(job.id)

    def create(self, url=URL, force=False):
        return self.client.post("/api/projects" + ("?force=true" if force else ""), json={"url": url})

    def completed_project(self, url=URL):
        project_id = self.create(url).json()["project"]["id"]
        self.process_next()
        return project_id


def make_harness(store, tmp_path, **setting_overrides):
    storage, clock = LocalArtifactStorage(tmp_path / "s"), FakeClock()
    settings = Settings(_env_file=None, **setting_overrides) if setting_overrides else None
    override(store, storage, clock, settings)
    return Harness(store, storage, clock)


@pytest.fixture
def harness(store, tmp_path):
    """Runs each API test once per Store implementation (memory, postgres)."""
    yield make_harness(store, tmp_path)
    app.dependency_overrides.clear()


@pytest.fixture
def memory_harness(tmp_path):
    """For the few tests that reach into or patch InMemoryStore itself."""
    yield make_harness(InMemoryStore(), tmp_path)
    app.dependency_overrides.clear()


@pytest.fixture
def limited_harness(store, tmp_path):
    def build(**overrides):
        return make_harness(store, tmp_path, **overrides)

    yield build
    app.dependency_overrides.clear()


def test_create_rejects_urls_longer_than_2048_characters(harness):
    response = harness.create("https://youtu.be/dQw4w9WgXcQ?x=" + "a" * 2048)

    assert response.status_code == 422


def test_create_is_refused_with_503_when_too_many_jobs_are_active(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    harness.create()

    response = harness.create(OTHER_URL)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert "Too many jobs" in response.json()["detail"]
    assert len(harness.store.list_live_projects()) == 1


def test_create_is_accepted_again_once_a_job_finishes(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    harness.create()
    harness.process_next()

    response = harness.create(OTHER_URL)

    assert response.status_code == 201


def test_create_is_refused_with_507_when_storage_is_full(limited_harness):
    harness = limited_harness(storage_max_bytes=1, storage_warn_bytes=1)
    harness.completed_project()

    response = harness.create(OTHER_URL)

    assert response.status_code == 507
    assert "Storage is full" in response.json()["detail"]


def test_duplicate_check_runs_before_admission(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    harness.create()

    response = harness.create()

    assert response.status_code == 409


def test_retry_is_refused_with_503_when_too_many_jobs_are_active(limited_harness):
    harness = limited_harness(max_active_jobs=1)
    failed_id = harness.create().json()["project"]["id"]
    harness.process_next(make_engines(extractor=FakeExtractor(error=AudioExtractionError("gone"))))
    harness.create(OTHER_URL)

    response = harness.client.post(f"/api/projects/{failed_id}/retry")

    assert response.status_code == 503


def test_create_logs_project_created_with_correlation_ids(harness, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.projects"):
        body = harness.create().json()

    event = logged_events(caplog, "project_created")[0]
    job = harness.store.get_job(body["job"]["id"])
    assert event["project_id"] == body["project"]["id"]
    assert event["job_id"] == job.id
    assert event["correlation_id"] == job.correlation_id
    assert event["request_id"]


def test_retry_logs_job_requeued_with_correlation_ids(harness, caplog):
    project_id = harness.create().json()["project"]["id"]
    job = harness.process_next(make_engines(extractor=FakeExtractor(error=AudioExtractionError("gone"))))

    with caplog.at_level(logging.INFO, logger="app.api.projects"):
        harness.client.post(f"/api/projects/{project_id}/retry")

    event = logged_events(caplog, "job_requeued")[0]
    assert event["job_id"] == job.id
    assert event["correlation_id"] == job.correlation_id


def test_create_enqueues_a_project_without_running_the_pipeline(harness):
    response = harness.create()

    body = response.json()
    assert response.status_code == 201
    assert body["project"]["title"] == URL
    assert body["project"]["source_url"] == URL
    assert body["job"]["status"] == "queued"
    assert body["project"]["latest_job"]["id"] == body["job"]["id"]
    assert harness.store.get_job(body["job"]["id"]).attempts == 0


def test_create_rejects_unsupported_urls(harness):
    response = harness.create("https://example.com/song")

    assert response.status_code == 422
    assert "not a supported YouTube URL" in response.json()["detail"]


def test_duplicate_source_reports_existing_project(harness):
    first = harness.create().json()["project"]["id"]

    response = harness.create("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert response.status_code == 409
    assert response.json()["existing_project_id"] == first


def test_forced_duplicate_creates_new_project_with_existing_title(harness):
    first = harness.completed_project()

    response = harness.create(force=True)

    assert response.status_code == 201
    assert response.json()["project"]["id"] != first
    assert response.json()["project"]["title"] == "Fake Song"


def test_list_returns_live_projects_with_status(harness):
    project_id = harness.completed_project()
    other = harness.create(OTHER_URL).json()["project"]["id"]
    harness.client.delete(f"/api/projects/{other}")

    response = harness.client.get("/api/projects")

    assert response.status_code == 200
    assert [(p["id"], p["latest_job_status"], p["has_edits"]) for p in response.json()] == [
        (project_id, "completed", False)
    ]


def test_get_project_and_404(harness):
    project_id = harness.create().json()["project"]["id"]

    found = harness.client.get(f"/api/projects/{project_id}")
    missing = harness.client.get(f"/api/projects/{MISSING}")

    assert found.status_code == 200
    assert found.json()["latest_job"]["status"] == "queued"
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "method, suffix",
    [
        ("GET", ""),
        ("DELETE", ""),
        ("POST", "/retry"),
        ("GET", "/analysis"),
        ("GET", "/diagnostics"),
        ("GET", "/audio/drums"),
        ("GET", "/score"),
        ("PUT", "/score"),
    ],
)
@pytest.mark.parametrize("project_id", ["abc", MISSING])
def test_malformed_or_unknown_project_id_is_404(harness, method, suffix, project_id):
    body = {"score": {"measures": []}} if method == "PUT" else None

    response = harness.client.request(method, f"/api/projects/{project_id}{suffix}", json=body)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_delete_soft_deletes_and_hides_project(harness):
    project_id = harness.create().json()["project"]["id"]

    deleted = harness.client.delete(f"/api/projects/{project_id}")
    again = harness.client.delete(f"/api/projects/{project_id}")

    assert deleted.status_code == 204
    assert again.status_code == 404
    assert harness.client.get(f"/api/projects/{project_id}").status_code == 404


def test_analysis_is_409_until_completed_then_returns_contract_shape(harness):
    project_id = harness.create().json()["project"]["id"]

    early = harness.client.get(f"/api/projects/{project_id}/analysis")
    harness.process_next()
    ready = harness.client.get(f"/api/projects/{project_id}/analysis")

    assert early.status_code == 409
    assert "job status is queued" in early.json()["detail"]
    body = ready.json()
    assert body["tempo_bpm"] == 120.0
    assert {e["id"] for e in body["events"]} == {"e1", "e2"}
    assert body["events"][0]["time"] == 0.5 + 1e-9
    assert body["events"][0]["measure"] is not None
    assert len(body["beats"]) == 4


def test_diagnostics_before_and_after_completion(harness):
    project_id = harness.create().json()["project"]["id"]

    early = harness.client.get(f"/api/projects/{project_id}/diagnostics")
    harness.process_next()
    ready = harness.client.get(f"/api/projects/{project_id}/diagnostics")

    assert early.status_code == 409
    assert ready.status_code == 200
    assert ready.json()["events"][0]["source_time"] == 0.5 + 1e-9


@pytest.mark.parametrize("stem, content", [("drums", b"fake drums"), ("accompaniment", b"fake accompaniment")])
def test_audio_is_served_from_storage(harness, stem, content):
    project_id = harness.completed_project()

    response = harness.client.get(f"/api/projects/{project_id}/audio/{stem}")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "audio/wav"


def test_audio_409_before_ready_and_422_for_unknown_stem(harness):
    project_id = harness.create().json()["project"]["id"]

    assert harness.client.get(f"/api/projects/{project_id}/audio/drums").status_code == 409
    assert harness.client.get(f"/api/projects/{project_id}/audio/vocals").status_code == 422


def test_audio_409_when_analysis_has_no_stem_artifact(memory_harness):
    project_id = memory_harness.completed_project()
    job = memory_harness.store.latest_job(project_id)
    store = memory_harness.store
    store._artifacts = {k: a for k, a in store._artifacts.items() if a.job_id != job.id}

    assert memory_harness.client.get(f"/api/projects/{project_id}/audio/drums").status_code == 409


def test_audio_410_when_pruned(harness):
    project_id = harness.completed_project()
    job = harness.store.latest_job(project_id)
    key = harness.store.artifacts_for_job(job.id)[ArtifactKind.DRUMS_STEM].storage_key
    harness.store.mark_storage_keys_pruned({key}, harness.clock())

    assert harness.client.get(f"/api/projects/{project_id}/audio/drums").status_code == 410


def test_responses_never_expose_storage_locations(harness, tmp_path):
    project_id = harness.completed_project()

    bodies = [
        harness.client.get("/api/projects").text,
        harness.client.get(f"/api/projects/{project_id}").text,
        harness.client.get(f"/api/projects/{project_id}/analysis").text,
    ]

    assert not any(str(tmp_path) in body or "projects/" in body for body in bodies)


def test_retry_requeues_failed_job_only(harness):
    project_id = harness.create().json()["project"]["id"]
    not_failed = harness.client.post(f"/api/projects/{project_id}/retry")
    harness.process_next(make_engines(extractor=FakeExtractor(error=AudioExtractionError("gone"))))

    retried = harness.client.post(f"/api/projects/{project_id}/retry")

    assert not_failed.status_code == 409
    assert retried.status_code == 202
    assert retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 0


def test_retry_is_409_when_the_job_stops_being_failed_before_the_requeue(memory_harness, monkeypatch):
    project_id = memory_harness.create().json()["project"]["id"]
    memory_harness.process_next(make_engines(extractor=FakeExtractor(error=AudioExtractionError("gone"))))
    monkeypatch.setattr(memory_harness.store, "requeue_failed_job", lambda job_id, now: None)

    response = memory_harness.client.post(f"/api/projects/{project_id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only a failed job can be retried; it was requeued or changed meanwhile"


def test_score_lifecycle(harness):
    project_id = harness.completed_project()
    score = {"measures": [[{"type": "rest", "id": "r1", "position": {"measure": 1, "beat": 1, "subdivision": 0}, "duration": "w"}]]}

    missing = harness.client.get(f"/api/projects/{project_id}/score")
    first = harness.client.put(f"/api/projects/{project_id}/score", json={"score": score, "base_version": None})
    loaded = harness.client.get(f"/api/projects/{project_id}/score")
    stale = harness.client.put(f"/api/projects/{project_id}/score", json={"score": score, "base_version": None})
    second = harness.client.put(f"/api/projects/{project_id}/score", json={"score": score, "base_version": 1})

    assert missing.status_code == 404
    assert first.status_code == 201
    assert first.json() == {"version": 1}
    assert loaded.json() == {"version": 1, "score": score}
    assert stale.status_code == 409
    assert stale.json()["latest_version"] == 1
    assert second.json() == {"version": 2}
    assert harness.client.get("/api/projects").json()[0]["has_edits"] is True


def test_score_save_validation(harness):
    project_id = harness.completed_project()
    queued = harness.create(OTHER_URL).json()["project"]["id"]

    malformed = harness.client.put(f"/api/projects/{project_id}/score", json={"score": {"bars": []}})
    not_ready = harness.client.put(f"/api/projects/{queued}/score", json={"score": {"measures": []}})
    unknown = harness.client.put(f"/api/projects/{MISSING}/score", json={"score": {"measures": []}})

    assert malformed.status_code == 422
    assert not_ready.status_code == 409
    assert unknown.status_code == 404


@pytest.mark.integration
def test_project_survives_restart_with_saved_edits(postgres_store, migrated_postgres_url, tmp_path):
    from app.persistence.postgres import create_postgres_store

    storage, clock = LocalArtifactStorage(tmp_path / "s"), FakeClock()
    try:
        override(postgres_store, storage, clock)
        before = TestClient(app)
        project_id = before.post("/api/projects", json={"url": URL}).json()["project"]["id"]
        job = postgres_store.claim_next_job("w", 300, clock())
        process_job(job, JobContext(postgres_store, storage, make_engines(), "w", 30, clock))
        before.put(f"/api/projects/{project_id}/score", json={"score": {"measures": [["edited"]]}, "base_version": None})

        restarted_store = create_postgres_store(migrated_postgres_url)
        override(restarted_store, storage, clock)
        after = TestClient(app)
        analysis = after.get(f"/api/projects/{project_id}/analysis")
        score = after.get(f"/api/projects/{project_id}/score")
        audio = after.get(f"/api/projects/{project_id}/audio/drums")
        restarted_store.engine.dispose()
    finally:
        app.dependency_overrides.clear()

    assert analysis.status_code == 200
    assert score.json() == {"version": 1, "score": {"measures": [["edited"]]}}
    assert audio.content == b"fake drums"
