import logging
from datetime import timedelta

import pytest

from app.audio_extraction import AudioExtractionError
from app.config import Settings
from app.stem_separation import StemSeparationError
from app.persistence.memory import InMemoryStore
from app.persistence.models import ArtifactKind, JobStatus, LeaseLostError
from app.pipeline.runner import JobAbandoned, JobContext, process_job
from app.storage import LocalArtifactStorage
from app.worker.pruner import prune
from tests.fakes import (
    FOUR_BEATS,
    SAMPLE_RAW_EVENTS,
    FakeBeatDetector,
    FakeClock,
    FakeExtractor,
    FakeMonotonic,
    FakeSeparator,
    FakeTranscriber,
    logged_events,
    make_engines,
)

URL = "https://youtu.be/dQw4w9WgXcQ"
KEY = "youtube:dQw4w9WgXcQ"
OWNER = "worker-a"


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def storage(tmp_path):
    return LocalArtifactStorage(tmp_path / "storage")


@pytest.fixture
def clock():
    return FakeClock()


def new_project(store, clock, title=URL):
    return store.create_project_with_job(
        source_kind="youtube", source_url=URL, source_key=KEY, title=title, max_attempts=3, now=clock()
    )


def run(store, storage, clock, engines, should_stop=lambda: False, monotonic=None):
    job = store.claim_next_job(OWNER, 300, clock())
    ctx = JobContext(
        store=store,
        storage=storage,
        engines=engines,
        owner=OWNER,
        retry_base_seconds=30,
        clock=clock,
        should_stop=should_stop,
        monotonic=monotonic or FakeMonotonic(),
    )
    process_job(job, ctx)
    return store.get_job(job.id)


def run_with_outcome(store, storage, clock, engines, monotonic=None):
    job = store.claim_next_job(OWNER, 300, clock())
    ctx = JobContext(
        store=store, storage=storage, engines=engines, owner=OWNER, retry_base_seconds=30, clock=clock,
        monotonic=monotonic or FakeMonotonic(),
    )
    return process_job(job, ctx), store.get_job(job.id)


def test_full_run_completes_job_with_analysis_artifacts_and_title(store, storage, clock):
    project, _ = new_project(store, clock)

    job = run(store, storage, clock, make_engines())

    assert job.status == JobStatus.COMPLETED
    analysis = store.latest_analysis(project.id)
    assert analysis.raw_events == SAMPLE_RAW_EVENTS
    assert [e.time for e in analysis.events] == [e.time for e in SAMPLE_RAW_EVENTS]
    assert all(e.measure is not None for e in analysis.events)
    assert analysis.beats == FOUR_BEATS
    assert analysis.pipeline_version == "1"
    artifacts = store.artifacts_for_job(job.id)
    assert set(artifacts) == set(ArtifactKind)
    assert storage.read_bytes(artifacts[ArtifactKind.DRUMS_STEM].storage_key) == b"fake drums"
    assert artifacts[ArtifactKind.DRUMS_STEM].storage_key == f"projects/{project.id}/{job.id}/drums.wav"
    assert store.get_project(project.id).title == "Fake Song"


def test_existing_custom_title_is_not_overwritten(store, storage, clock):
    project, _ = new_project(store, clock, title="My Title")

    run(store, storage, clock, make_engines())

    assert store.get_project(project.id).title == "My Title"


def test_retry_resumes_after_last_committed_stage(store, storage, clock):
    new_project(store, clock)
    extractor = FakeExtractor()
    first = run(store, storage, clock, make_engines(extractor=extractor, separator=FakeSeparator(error=RuntimeError("oom"))))
    clock.advance(31)

    second = run(store, storage, clock, make_engines(extractor=extractor))

    assert first.status == JobStatus.SEPARATING_STEMS
    assert first.error == "Unexpected error: oom"
    assert second.status == JobStatus.COMPLETED
    assert extractor.calls == 1


def test_forced_duplicate_reuses_cached_stage_outputs(store, storage, clock):
    extractor, separator, transcriber = FakeExtractor(), FakeSeparator(), FakeTranscriber()
    engines = make_engines(extractor=extractor, separator=separator, transcriber=transcriber)
    original, _ = new_project(store, clock)
    first = run(store, storage, clock, engines)
    duplicate, _ = new_project(store, clock)

    second = run(store, storage, clock, engines)

    assert second.status == JobStatus.COMPLETED
    assert (extractor.calls, separator.calls, transcriber.calls) == (1, 1, 1)
    original_keys = {k: a.storage_key for k, a in store.artifacts_for_job(first.id).items()}
    duplicate_keys = {k: a.storage_key for k, a in store.artifacts_for_job(second.id).items()}
    assert duplicate_keys == {k: key for k, key in original_keys.items() if k != ArtifactKind.SOURCE_AUDIO}
    assert store.latest_analysis(duplicate.id).raw_events == store.latest_analysis(original.id).raw_events


def test_forced_duplicate_after_source_audio_was_pruned_does_not_download_again(store, storage, clock):
    extractor, separator, transcriber = FakeExtractor(), FakeSeparator(), FakeTranscriber()
    engines = make_engines(extractor=extractor, separator=separator, transcriber=transcriber)
    original, _ = new_project(store, clock)
    first = run(store, storage, clock, engines)
    pruned = prune(store, storage, clock(), Settings(_env_file=None))
    duplicate, _ = new_project(store, clock, title=store.get_project(original.id).title)

    second = run(store, storage, clock, engines)

    assert pruned.deleted_keys == 1
    assert second.status == JobStatus.COMPLETED
    assert (extractor.calls, separator.calls, transcriber.calls) == (1, 1, 1)
    original_keys = {k: a.storage_key for k, a in store.artifacts_for_job(first.id).items()}
    duplicate_keys = {k: a.storage_key for k, a in store.artifacts_for_job(second.id).items()}
    assert set(duplicate_keys) == {ArtifactKind.DRUMS_STEM, ArtifactKind.ACCOMPANIMENT_STEM, ArtifactKind.RAW_TRANSCRIPTION}
    assert all(duplicate_keys[kind] == original_keys[kind] for kind in duplicate_keys)
    assert store.latest_analysis(duplicate.id).events == store.latest_analysis(original.id).events
    assert store.get_project(duplicate.id).title == "Fake Song"


def test_resumed_job_whose_source_was_pruned_after_separation_does_not_extract_again(store, storage, clock):
    _, job = new_project(store, clock)
    extractor = FakeExtractor()
    first = run(store, storage, clock, make_engines(extractor=extractor, transcriber=FakeTranscriber(error=RuntimeError("x"))))
    source_key = store.artifacts_for_job(first.id)[ArtifactKind.SOURCE_AUDIO].storage_key
    storage.delete(source_key)
    store.mark_storage_keys_pruned({source_key}, clock())
    clock.advance(31)

    second = run(store, storage, clock, make_engines(extractor=extractor))

    assert second.status == JobStatus.COMPLETED
    assert extractor.calls == 1


def test_each_stage_logs_start_and_finish_with_its_duration(store, storage, clock, caplog):
    monotonic = FakeMonotonic()
    engines = make_engines(separator=FakeSeparator(on_call=lambda: monotonic.advance(2.5)))
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        outcome, _ = run_with_outcome(store, storage, clock, engines, monotonic)

    assert outcome == "completed"
    assert [e["stage"] for e in logged_events(caplog, "stage_started")] == ["extract", "separate", "transcribe", "map_tempo"]
    finished = {e["stage"]: e for e in logged_events(caplog, "stage_finished")}
    assert finished["separate"] == {"stage": "separate", "duration_ms": 2500, "outcome": "ran"}
    assert finished["extract"]["duration_ms"] == 0
    assert set(finished) == {"extract", "separate", "transcribe", "map_tempo"}


def test_reused_stages_log_a_cached_finish_without_a_start(store, storage, clock, caplog):
    # Importing app.main (e.g. via test_projects_api.py at collection time)
    # permanently raises the root logger to INFO for the rest of the
    # session, so the untracked first run below must be pinned back down
    # or its stage events leak into this test's caplog capture too.
    caplog.set_level(logging.WARNING, logger="app.pipeline.runner")
    engines = make_engines()
    new_project(store, clock)
    run(store, storage, clock, engines)
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        run(store, storage, clock, engines)

    assert [e["stage"] for e in logged_events(caplog, "stage_started")] == ["map_tempo"]
    cached = [e for e in logged_events(caplog, "stage_finished") if e["outcome"] == "cached"]
    assert [e["stage"] for e in cached] == ["separate", "transcribe"]


def test_failing_stage_logs_stage_failed_and_the_job_fails(store, storage, clock, caplog):
    monotonic = FakeMonotonic()
    error = StemSeparationError("Demucs failed: bad input")
    engines = make_engines(separator=FakeSeparator(error=error, on_call=lambda: monotonic.advance(1)))
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        outcome, job = run_with_outcome(store, storage, clock, engines, monotonic)

    assert outcome == "failed"
    assert job.status == JobStatus.FAILED
    assert logged_events(caplog, "stage_failed") == [
        {"stage": "separate", "duration_ms": 1000, "error_type": "StemSeparationError", "permanent": True}
    ]
    assert [e["stage"] for e in logged_events(caplog, "stage_finished")] == ["extract"]


def test_transient_failure_reports_retry_scheduled(store, storage, clock, caplog):
    engines = make_engines(separator=FakeSeparator(error=OSError("disk hiccup")))
    new_project(store, clock)

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        outcome, job = run_with_outcome(store, storage, clock, engines)

    assert outcome == "retry_scheduled"
    assert logged_events(caplog, "stage_failed")[0]["permanent"] is False


def test_deleted_project_reports_failed(store, storage, clock):
    project, _ = new_project(store, clock)
    store.soft_delete_project(project.id, clock())

    outcome, job = run_with_outcome(store, storage, clock, make_engines())

    assert outcome == "failed"
    assert job.error == "Project was deleted"


def test_cache_entry_with_missing_file_is_ignored(store, storage, clock):
    separator = FakeSeparator()
    engines = make_engines(separator=separator)
    new_project(store, clock)
    first = run(store, storage, clock, engines)
    storage.delete(store.artifacts_for_job(first.id)[ArtifactKind.DRUMS_STEM].storage_key)
    new_project(store, clock)

    second = run(store, storage, clock, engines)

    assert second.status == JobStatus.COMPLETED
    assert separator.calls == 2


def test_committed_artifact_whose_file_vanished_is_recomputed(store, storage, clock):
    new_project(store, clock)
    extractor = FakeExtractor()
    first = run(store, storage, clock, make_engines(extractor=extractor, separator=FakeSeparator(error=RuntimeError("x"))))
    storage.delete(store.artifacts_for_job(first.id)[ArtifactKind.SOURCE_AUDIO].storage_key)
    clock.advance(31)

    second = run(store, storage, clock, make_engines(extractor=extractor))

    assert second.status == JobStatus.COMPLETED
    assert extractor.calls == 2


def test_permanent_error_fails_immediately(store, storage, clock):
    new_project(store, clock)

    job = run(store, storage, clock, make_engines(extractor=FakeExtractor(error=AudioExtractionError("video unavailable"))))

    assert job.status == JobStatus.FAILED
    assert job.error == "video unavailable"
    assert job.attempts == 1


def test_insufficient_beats_fails_with_message(store, storage, clock):
    new_project(store, clock)

    job = run(store, storage, clock, make_engines(beat_detector=FakeBeatDetector(FOUR_BEATS[:1])))

    assert job.status == JobStatus.FAILED
    assert job.error == "Beat detection found only 1 beat(s); tempo mapping requires at least 2"


def test_transient_error_schedules_retry_with_backoff(store, storage, clock):
    new_project(store, clock)
    started = clock()

    job = run(store, storage, clock, make_engines(transcriber=FakeTranscriber(error=RuntimeError("boom"))))

    assert job.status == JobStatus.TRANSCRIBING
    assert job.error == "Unexpected error: boom"
    assert job.available_at == started + timedelta(seconds=30)
    assert job.lease_owner is None


def test_transient_error_on_last_attempt_fails_job(store, storage, clock):
    new_project(store, clock)
    engines = make_engines(transcriber=FakeTranscriber(error=RuntimeError("boom")))
    run(store, storage, clock, engines)
    clock.advance(30)
    run(store, storage, clock, engines)
    clock.advance(60)

    job = run(store, storage, clock, engines)

    assert job.status == JobStatus.FAILED
    assert job.error == "Unexpected error: boom"
    assert job.attempts == 3


def test_deleted_project_job_is_failed_without_running(store, storage, clock):
    project, _ = new_project(store, clock)
    store.soft_delete_project(project.id, clock())
    extractor = FakeExtractor()

    job = run(store, storage, clock, make_engines(extractor=extractor))

    assert job.status == JobStatus.FAILED
    assert job.error == "Project was deleted"
    assert extractor.calls == 0


def test_stop_request_abandons_between_stages_after_committing_output(store, storage, clock):
    _, job = new_project(store, clock)
    stop = {"requested": False}
    extractor = FakeExtractor(on_call=lambda: stop.update(requested=True))

    with pytest.raises(JobAbandoned):
        run(store, storage, clock, make_engines(extractor=extractor), should_stop=lambda: stop["requested"])

    assert ArtifactKind.SOURCE_AUDIO in store.artifacts_for_job(job.id)
    assert store.get_job(job.id).status == JobStatus.DOWNLOADED


def test_engine_error_after_a_stop_request_abandons_instead_of_failing(store, storage, clock):
    _, job = new_project(store, clock)
    stop = {"requested": False}
    separator = FakeSeparator(
        error=StemSeparationError("Demucs failed: interrupted"), on_call=lambda: stop.update(requested=True)
    )

    with pytest.raises(JobAbandoned):
        run(store, storage, clock, make_engines(separator=separator), should_stop=lambda: stop["requested"])

    abandoned = store.get_job(job.id)
    assert abandoned.status == JobStatus.SEPARATING_STEMS
    assert abandoned.error is None
    assert abandoned.finished_at is None
    assert abandoned.available_at == clock()
    assert abandoned.lease_owner == OWNER


def test_transient_error_after_a_stop_request_does_not_schedule_a_retry(store, storage, clock):
    _, job = new_project(store, clock)
    stop = {"requested": False}
    separator = FakeSeparator(error=RuntimeError("killed"), on_call=lambda: stop.update(requested=True))

    with pytest.raises(JobAbandoned):
        run(store, storage, clock, make_engines(separator=separator), should_stop=lambda: stop["requested"])

    assert store.get_job(job.id).error is None
    assert store.get_job(job.id).available_at == clock()


def test_lost_lease_propagates_and_commits_nothing(store, storage, clock):
    _, job = new_project(store, clock)

    def steal():
        store.claim_next_job("thief", 300, clock() + timedelta(days=1))

    with pytest.raises(LeaseLostError):
        run(store, storage, clock, make_engines(extractor=FakeExtractor(on_call=steal)))

    assert store.artifacts_for_job(job.id) == {}
    assert store.get_job(job.id).lease_owner == "thief"


def test_stored_job_error_is_sanitized_but_the_log_keeps_the_raw_text(store, storage, clock, caplog, tmp_path):
    new_project(store, clock)
    leaked = tmp_path / "secret" / "source.wav"
    engines = make_engines(separator=FakeSeparator(error=StemSeparationError(f"Demucs failed: cannot read {leaked}")))
    job = store.claim_next_job(OWNER, 300, clock())
    ctx = JobContext(
        store=store, storage=storage, engines=engines, owner=OWNER, retry_base_seconds=30, clock=clock,
        error_roots=((tmp_path, "<storage>"),),
    )

    with caplog.at_level(logging.INFO, logger="app.pipeline.runner"):
        process_job(job, ctx)

    stored = store.get_job(job.id).error
    assert stored.startswith("Demucs failed: cannot read <storage>")
    assert stored.endswith("source.wav")
    assert str(tmp_path) not in stored
    assert str(leaked) in caplog.text
