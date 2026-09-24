import logging
import threading
import time
from datetime import timedelta

import pytest

from app.config import Settings
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind, JobStatus
from app.storage import LocalArtifactStorage
from app.worker import worker as worker_module
from app.worker.worker import Worker, default_owner
from tests.fakes import FakeClock, FakeExtractor, make_engines


def settings(**overrides):
    values = {"heartbeat_seconds": 0.01, "poll_interval_seconds": 0.01}
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def parts(tmp_path):
    return InMemoryStore(), LocalArtifactStorage(tmp_path / "s"), FakeClock()


def enqueue(store, clock):
    return store.create_project_with_job(
        source_kind="youtube", source_url="https://youtu.be/dQw4w9WgXcQ", source_key="youtube:dQw4w9WgXcQ",
        title="https://youtu.be/dQw4w9WgXcQ", max_attempts=3, now=clock(),
    )


def make_worker(store, storage, clock, engines=None, **setting_overrides):
    return Worker(
        store=store, storage=storage, engines=engines or make_engines(), settings=settings(**setting_overrides),
        clock=clock, owner="w1", jitter=lambda low, high: 0.0,
    )


def test_default_owner_is_unique_per_call():
    assert default_owner() != default_owner()


def test_worker_generates_an_owner_when_none_is_given(parts):
    store, storage, clock = parts

    worker = Worker(store=store, storage=storage, engines=make_engines(), settings=settings())

    assert worker.owner


def test_run_once_returns_false_when_queue_is_empty(parts):
    store, storage, clock = parts

    assert make_worker(store, storage, clock).run_once() is False


def test_run_once_processes_a_job_to_completion(parts):
    store, storage, clock = parts
    project, job = enqueue(store, clock)

    processed = make_worker(store, storage, clock).run_once()

    assert processed is True
    assert store.get_job(job.id).status == JobStatus.COMPLETED
    assert store.latest_analysis(project.id) is not None


def test_job_past_max_attempts_is_failed_without_running(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    for _ in range(3):
        store.claim_next_job("crashed", 300, clock())
        clock.advance(301)
    extractor = FakeExtractor()

    make_worker(store, storage, clock, make_engines(extractor=extractor)).run_once()

    failed = store.get_job(job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.error == "Exceeded maximum attempts"
    assert extractor.calls == 0


def test_stop_during_a_job_releases_the_lease_after_the_current_stage(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    holder = {}
    worker = make_worker(store, storage, clock, make_engines(extractor=FakeExtractor(on_call=lambda: holder["w"].stop())))
    holder["w"] = worker

    worker.run_once()

    released = store.get_job(job.id)
    assert released.lease_owner is None
    assert released.status == JobStatus.DOWNLOADED
    assert ArtifactKind.SOURCE_AUDIO in store.artifacts_for_job(job.id)
    assert store.claim_next_job("w2", 300, clock()).id == job.id


def test_lost_lease_is_logged_not_raised(parts, caplog):
    store, storage, clock = parts
    _, job = enqueue(store, clock)

    def steal():
        store.claim_next_job("thief", 300, clock() + timedelta(days=1))

    make_worker(store, storage, clock, make_engines(extractor=FakeExtractor(on_call=steal))).run_once()

    assert store.get_job(job.id).lease_owner == "thief"
    assert "Lost lease" in caplog.text


def test_maybe_prune_runs_at_most_once_per_interval(parts, monkeypatch):
    store, storage, clock = parts
    calls = []
    monkeypatch.setattr(worker_module, "prune", lambda *args: calls.append(args))
    worker = make_worker(store, storage, clock, prune_interval_seconds=3600)

    worker.maybe_prune()
    worker.maybe_prune()
    clock.advance(3600)
    worker.maybe_prune()

    assert len(calls) == 2


def test_run_forever_drains_the_queue_until_stopped(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    worker = make_worker(store, storage, clock)
    thread = threading.Thread(target=worker.run_forever)

    thread.start()
    deadline = time.monotonic() + 5
    while store.get_job(job.id).status != JobStatus.COMPLETED and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    thread.join(timeout=5)

    assert store.get_job(job.id).status == JobStatus.COMPLETED
    assert not thread.is_alive()


class FlakyOnceStore:
    """Delegates to `inner`, except the first call to `claim_next_job`
    raises a transient error, like a momentary DB outage."""

    def __init__(self, inner):
        self._inner = inner
        self._raised = False

    def claim_next_job(self, *args, **kwargs):
        if not self._raised:
            self._raised = True
            raise ConnectionError("db blip")
        return self._inner.claim_next_job(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_run_forever_survives_a_transient_store_error_and_keeps_running(parts, caplog):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    flaky_store = FlakyOnceStore(store)
    worker = make_worker(flaky_store, storage, clock)
    thread = threading.Thread(target=worker.run_forever)

    with caplog.at_level(logging.ERROR):
        thread.start()
        deadline = time.monotonic() + 5
        while store.get_job(job.id).status != JobStatus.COMPLETED and time.monotonic() < deadline:
            time.sleep(0.01)
        worker.stop()
        thread.join(timeout=5)

    assert store.get_job(job.id).status == JobStatus.COMPLETED
    assert not thread.is_alive()
    assert "db blip" in caplog.text or "ConnectionError" in caplog.text
