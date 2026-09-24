from datetime import UTC, datetime, timedelta

import pytest

from app.persistence.models import JobStatus, NewAnalysis, ScoreVersionConflictError
from app.timing import BeatPoint, TempoMap
from app.transcription import DrumEvent, DrumInstrument

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
OWNER = "worker-a"
LEASE = 300


def create(store, key="youtube:abc", now=NOW, url="https://youtu.be/abc", title=None):
    return store.create_project_with_job(
        source_kind="youtube",
        source_url=url,
        source_key=key,
        title=title or url,
        max_attempts=3,
        now=now,
    )


def sample_analysis():
    raw = [DrumEvent(id="e1", time=0.1 + 0.2, instrument=DrumInstrument.KICK, provenance="drumscript")]
    quantized = [DrumEvent(id="e1", time=0.1 + 0.2, instrument=DrumInstrument.KICK, provenance="drumscript", measure=1, beat=1, subdivision=0)]
    return NewAnalysis(
        pipeline_version="1",
        tempo_bpm=120.0,
        tempo_map=TempoMap.constant(120.0),
        beats=[BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True), BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False)],
        events=quantized,
        raw_events=raw,
    )


def complete(store, job_id, now=NOW):
    store.claim_next_job(OWNER, LEASE, now)
    return store.complete_job(job_id, OWNER, sample_analysis(), now)


def test_create_project_with_job_returns_queued_job(store):
    project, job = create(store)

    assert project.source_key == "youtube:abc"
    assert project.title == "https://youtu.be/abc"
    assert project.created_at == NOW
    assert project.deleted_at is None
    assert job.project_id == project.id
    assert job.status == JobStatus.QUEUED
    assert job.attempts == 0
    assert job.max_attempts == 3
    assert job.available_at == NOW
    assert job.lease_owner is None
    assert job.correlation_id


def test_get_project_and_job_round_trip(store):
    project, job = create(store)

    assert store.get_project(project.id) == project
    assert store.get_job(job.id) == job
    assert store.latest_job(project.id) == job


def test_unknown_ids_return_none(store):
    missing = "00000000-0000-0000-0000-000000000000"

    assert store.get_project(missing) is None
    assert store.get_job(missing) is None
    assert store.latest_job(missing) is None
    assert store.latest_analysis(missing) is None
    assert store.latest_score(missing) is None


def test_find_live_project_by_source_key_ignores_deleted_and_other_sources(store):
    deleted, _ = create(store, now=NOW)
    store.soft_delete_project(deleted.id, NOW)
    live, _ = create(store, now=NOW + timedelta(minutes=1))
    create(store, key="youtube:other")

    assert store.find_live_project_by_source_key("youtube:abc") == store.get_project(live.id)
    assert store.find_live_project_by_source_key("youtube:none") is None


def test_list_live_projects_most_recently_updated_first_with_status_and_edit_flag(store):
    edited, edited_job = create(store, key="youtube:a", now=NOW)
    analysis = complete(store, edited_job.id, now=NOW + timedelta(minutes=1))
    untouched, _ = create(store, key="youtube:b", now=NOW + timedelta(minutes=2))
    store.save_score(edited.id, analysis.id, {"measures": []}, None, NOW + timedelta(minutes=3))
    gone, _ = create(store, key="youtube:c", now=NOW + timedelta(minutes=4))
    store.soft_delete_project(gone.id, NOW + timedelta(minutes=5))

    summaries = store.list_live_projects()

    assert [s.project.id for s in summaries] == [edited.id, untouched.id]
    assert summaries[0].latest_job_status == JobStatus.COMPLETED
    assert summaries[0].has_edits is True
    assert summaries[1].latest_job_status == JobStatus.QUEUED
    assert summaries[1].has_edits is False


def test_set_project_title_updates_title_and_timestamp(store):
    project, _ = create(store)

    store.set_project_title(project.id, "Song Title", NOW + timedelta(seconds=5))

    updated = store.get_project(project.id)
    assert updated.title == "Song Title"
    assert updated.updated_at == NOW + timedelta(seconds=5)


def test_soft_delete_project_marks_once(store):
    project, _ = create(store)

    first = store.soft_delete_project(project.id, NOW)
    second = store.soft_delete_project(project.id, NOW)

    assert first is True
    assert second is False
    assert store.get_project(project.id).deleted_at == NOW
    assert store.soft_delete_project("00000000-0000-0000-0000-000000000000", NOW) is False


def test_complete_job_persists_analysis_with_exact_source_times(store):
    project, job = create(store)

    analysis = complete(store, job.id)

    loaded = store.latest_analysis(project.id)
    assert loaded == analysis
    assert loaded.job_id == job.id
    assert loaded.events[0].time == 0.1 + 0.2
    assert loaded.raw_events[0].measure is None
    assert loaded.beats == sample_analysis().beats
    assert loaded.tempo_map == TempoMap.constant(120.0)


def test_save_score_versions_increase_and_latest_is_returned(store):
    project, job = create(store)
    analysis = complete(store, job.id)

    first = store.save_score(project.id, analysis.id, {"measures": [["a"]]}, None, NOW)
    second = store.save_score(project.id, analysis.id, {"measures": [["b"]]}, 1, NOW + timedelta(seconds=1))

    assert first.version == 1
    assert second.version == 2
    assert store.latest_score(project.id) == second
    assert store.latest_score(project.id).score == {"measures": [["b"]]}


def test_save_score_with_stale_base_version_conflicts(store):
    project, job = create(store)
    analysis = complete(store, job.id)
    store.save_score(project.id, analysis.id, {"measures": []}, None, NOW)
    store.save_score(project.id, analysis.id, {"measures": []}, 1, NOW)

    with pytest.raises(ScoreVersionConflictError) as error:
        store.save_score(project.id, analysis.id, {"measures": []}, 1, NOW)

    assert error.value.latest_version == 2


def test_first_save_with_a_base_version_conflicts(store):
    project, job = create(store)
    analysis = complete(store, job.id)

    with pytest.raises(ScoreVersionConflictError) as error:
        store.save_score(project.id, analysis.id, {"measures": []}, 3, NOW)

    assert error.value.latest_version is None
