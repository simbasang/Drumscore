import pytest

from app.config import Settings
from app.persistence.models import JobStatus
from app.storage import LocalArtifactStorage
from app.worker.worker import Worker
from tests.fakes import FakeClock, FakeExtractor, FakeSeparator, FakeTranscriber, make_engines

pytestmark = pytest.mark.integration


class SimulatedCrash(BaseException):
    """Escapes process_job's `except Exception`, like the process being killed mid-stage."""


def settings():
    return Settings(_env_file=None, heartbeat_seconds=3600, poll_interval_seconds=0.01)


def enqueue(store, clock, video_id):
    url = f"https://youtu.be/{video_id}"
    return store.create_project_with_job(
        source_kind="youtube", source_url=url, source_key=f"youtube:{video_id}", title=url, max_attempts=3, now=clock()
    )


def test_job_survives_a_worker_crash_and_resumes_on_another_worker(postgres_store, tmp_path):
    clock = FakeClock()
    storage = LocalArtifactStorage(tmp_path)
    project, job = enqueue(postgres_store, clock, "dQw4w9WgXcQ")
    extractor, separator = FakeExtractor(), FakeSeparator()
    crashing = Worker(
        store=postgres_store, storage=storage, settings=settings(), clock=clock, owner="a",
        engines=make_engines(extractor=extractor, separator=separator, transcriber=FakeTranscriber(error=SimulatedCrash())),
    )
    with pytest.raises(SimulatedCrash):
        crashing.run_once()
    clock.advance(301)
    survivor = Worker(
        store=postgres_store, storage=storage, settings=settings(), clock=clock, owner="b",
        engines=make_engines(extractor=extractor, separator=separator),
    )

    survivor.run_once()

    finished = postgres_store.get_job(job.id)
    assert finished.status == JobStatus.COMPLETED
    assert finished.attempts == 2
    assert (extractor.calls, separator.calls) == (1, 1)
    assert postgres_store.latest_analysis(project.id) is not None


def test_two_workers_process_two_jobs_once_each(postgres_store, tmp_path):
    clock = FakeClock()
    storage = LocalArtifactStorage(tmp_path)
    enqueue(postgres_store, clock, "aaaaaaaaaaa")
    enqueue(postgres_store, clock, "bbbbbbbbbbb")
    separator = FakeSeparator()
    workers = [
        Worker(store=postgres_store, storage=storage, settings=settings(), clock=clock, owner=name,
               engines=make_engines(separator=separator))
        for name in ("a", "b")
    ]

    results = [worker.run_once() for worker in workers] + [worker.run_once() for worker in workers]

    assert results == [True, True, False, False]
    assert separator.calls == 2
    assert {s.latest_job_status for s in postgres_store.list_live_projects()} == {JobStatus.COMPLETED}
