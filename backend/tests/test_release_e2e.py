"""V1-035 release gate: one project driven through the whole lifecycle via
the real API, a real Worker and Postgres (engines faked). See
docs/RELEASE_CHECKLIST.md for the browser half of the gate."""

import pytest
from fastapi.testclient import TestClient

from app.audio_extraction import AudioExtractionError
from app.config import Settings
from app.main import app
from app.storage import LocalArtifactStorage
from app.worker.pruner import prune
from app.worker.worker import Worker
from tests.fakes import FakeClock, FakeExtractor, FakeSeparator, FakeTranscriber, make_engines
from tests.test_projects_api import URL, override

pytestmark = pytest.mark.integration

SCORE = {"measures": [[{"type": "rest", "id": "r1", "position": {"measure": 1, "beat": 1, "subdivision": 0}, "duration": "w"}]]}


class SimulatedKill(BaseException):
    """Escapes process_job's `except Exception`, like the worker process being killed mid-stage."""


class Release:
    def __init__(self, store, tmp_path):
        self.store, self.storage, self.clock = store, LocalArtifactStorage(tmp_path / "s"), FakeClock()
        self.settings = Settings(_env_file=None, heartbeat_seconds=299, poll_interval_seconds=0.01)
        self.connect(store)

    def connect(self, store):
        self.store = store
        override(store, self.storage, self.clock)
        self.client = TestClient(app)

    def worker(self, owner="w", **engines):
        return Worker(store=self.store, storage=self.storage, settings=self.settings, clock=self.clock,
                      owner=owner, engines=make_engines(**engines))

    def create(self, force=False):
        return self.client.post("/api/projects" + ("?force=true" if force else ""), json={"url": URL})

    def get(self, project_id, suffix=""):
        return self.client.get(f"/api/projects/{project_id}{suffix}")

    def job_status(self, project_id):
        return self.get(project_id).json()["latest_job"]["status"]


@pytest.fixture
def release(postgres_store, tmp_path):
    yield Release(postgres_store, tmp_path)
    app.dependency_overrides.clear()


def test_release_happy_path_submit_process_save_restart_reload(release, migrated_postgres_url):
    from app.persistence.postgres import create_postgres_store

    extractor, separator = FakeExtractor(), FakeSeparator()
    created = release.create()
    project_id = created.json()["project"]["id"]
    before_processing = release.get(project_id, "/analysis")
    processed = release.worker(extractor=extractor, separator=separator).run_once()
    status = release.job_status(project_id)
    analysis = release.get(project_id, "/analysis")
    diagnostics = release.get(project_id, "/diagnostics")
    stems = [release.get(project_id, f"/audio/{stem}").content for stem in ("drums", "accompaniment")]
    saved = release.client.put(f"/api/projects/{project_id}/score", json={"score": SCORE, "base_version": None})
    stale = release.client.put(f"/api/projects/{project_id}/score", json={"score": SCORE, "base_version": None})

    restarted_store = create_postgres_store(migrated_postgres_url)
    try:
        release.connect(restarted_store)
        reloaded_status = release.job_status(project_id)
        reloaded_analysis = release.get(project_id, "/analysis")
        reloaded_score = release.get(project_id, "/score")
        reprocessed = release.worker(owner="after-restart", extractor=extractor, separator=separator).run_once()
    finally:
        restarted_store.engine.dispose()

    assert created.status_code == 201
    assert created.json()["project"]["latest_job"]["status"] == "queued"
    assert before_processing.status_code == 409
    assert processed is True
    assert status == "completed"
    assert analysis.status_code == 200
    assert [event["time"] for event in analysis.json()["events"]] == [0.5 + 1e-9, 0.5 + 1e-9]
    assert diagnostics.status_code == 200
    assert stems == [b"fake drums", b"fake accompaniment"]
    assert saved.json() == {"version": 1}
    assert stale.status_code == 409
    assert stale.json()["latest_version"] == 1
    assert reloaded_status == "completed"
    assert reloaded_analysis.json() == analysis.json()
    assert reloaded_score.json() == {"version": 1, "score": SCORE}
    assert reprocessed is False
    assert (extractor.calls, separator.calls) == (1, 1)


def test_release_failure_then_retry_completes(release):
    project_id = release.create().json()["project"]["id"]
    release.worker(extractor=FakeExtractor(error=AudioExtractionError("video unavailable"))).run_once()
    failed = release.get(project_id).json()["latest_job"]

    retried = release.client.post(f"/api/projects/{project_id}/retry")
    release.worker().run_once()

    assert failed["status"] == "failed"
    assert "video unavailable" in failed["error"]
    assert retried.status_code == 202
    assert retried.json()["status"] == "queued"
    assert release.job_status(project_id) == "completed"
    assert release.get(project_id, "/analysis").status_code == 200


def test_release_worker_crash_resumes_without_redoing_finished_stages(release):
    extractor, separator = FakeExtractor(), FakeSeparator()
    project_id = release.create().json()["project"]["id"]
    killed = release.worker(owner="a", extractor=extractor, separator=separator,
                            transcriber=FakeTranscriber(error=SimulatedKill()))
    with pytest.raises(SimulatedKill):
        killed.run_once()
    status_after_kill = release.job_status(project_id)
    release.clock.advance(301)

    release.worker(owner="b", extractor=extractor, separator=separator).run_once()

    assert status_after_kill != "completed"
    assert release.job_status(project_id) == "completed"
    assert (extractor.calls, separator.calls) == (1, 1)
    assert release.get(project_id, "/analysis").status_code == 200


def test_release_duplicate_reuses_cache_and_delete_reclaims_storage(release):
    first = release.create().json()["project"]["id"]
    release.worker().run_once()
    extractor, separator = FakeExtractor(), FakeSeparator()
    duplicate = release.create(force=True).json()["project"]["id"]
    release.worker(extractor=extractor, separator=separator).run_once()
    duplicate_status = release.job_status(duplicate)
    bytes_before_delete = release.storage.total_bytes()

    deletes = [release.client.delete(f"/api/projects/{project_id}").status_code for project_id in (first, duplicate)]
    prune(release.store, release.storage, release.clock(), release.settings)

    assert duplicate_status == "completed"
    assert (extractor.calls, separator.calls) == (0, 0)
    assert bytes_before_delete > 0
    assert deletes == [204, 204]
    assert release.storage.total_bytes() == 0
    assert release.client.get("/api/projects").json() == []
