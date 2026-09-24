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
from app.stem_separation import StemSeparationError
from tests.fakes import FakeClock, FakeExtractor, FakeSeparator, make_engines


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


def test_stop_that_kills_the_engine_releases_the_lease_and_refunds_the_attempt(parts):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    holder = {}

    def stop_and_lose_the_child():
        holder["w"].stop()
        raise StemSeparationError("Demucs failed: interrupted")

    separator = FakeSeparator(on_call=stop_and_lose_the_child)
    worker = make_worker(store, storage, clock, make_engines(separator=separator))
    holder["w"] = worker

    worker.run_once()

    released = store.get_job(job.id)
    assert released.status == JobStatus.SEPARATING_STEMS
    assert released.error is None
    assert released.lease_owner is None
    assert released.attempts == 0
    assert store.claim_next_job("w2", 300, clock()).id == job.id


class LeaseStolenAfterFirstCommitStore:
    """Delegates to `inner`. Right after the first committed stage another
    worker reclaims the job, and the call returns only once the heartbeat
    has been refused, so `heartbeat.lost` is set before the runner's next
    checkpoint. Records every release_lease call."""

    def __init__(self, inner, clock):
        self._inner = inner
        self._clock = clock
        self._stolen = False
        self.refused_extensions = 0
        self.releases = []

    def commit_stage(self, *args, **kwargs):
        created = self._inner.commit_stage(*args, **kwargs)
        if not self._stolen:
            self._stolen = True
            self._inner.claim_next_job("thief", 300, self._clock() + timedelta(days=1))
            deadline = time.monotonic() + 5
            while self.refused_extensions == 0 and time.monotonic() < deadline:
                time.sleep(0.005)
        return created

    def extend_lease(self, *args, **kwargs):
        extended = self._inner.extend_lease(*args, **kwargs)
        if not extended:
            self.refused_extensions += 1
        return extended

    def release_lease(self, *args, **kwargs):
        self.releases.append(args)
        return self._inner.release_lease(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_lost_heartbeat_abandons_the_job_and_releases_nothing(parts, caplog):
    store, storage, clock = parts
    _, job = enqueue(store, clock)
    stealing = LeaseStolenAfterFirstCommitStore(store, clock)
    separator = FakeSeparator()

    with caplog.at_level(logging.INFO):
        make_worker(stealing, storage, clock, make_engines(separator=separator)).run_once()

    stolen = store.get_job(job.id)
    assert stealing.releases == []
    assert stolen.lease_owner == "thief"
    assert stolen.attempts == 2
    assert stolen.status == JobStatus.DOWNLOADED
    assert separator.calls == 0
    assert "abandoned job" in caplog.text


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
