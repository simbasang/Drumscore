from datetime import UTC, datetime, timedelta

import pytest

from app.persistence.models import (
    ArtifactKind,
    CacheEntry,
    JobStatus,
    LeaseLostError,
    NewAnalysis,
    NewArtifact,
    ScoreVersionConflictError,
    Stage,
)
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


def descriptor(kind=ArtifactKind.SOURCE_AUDIO, key="projects/p/j/source.wav"):
    return NewArtifact(kind=kind, storage_key=key, size_bytes=4, sha256="deadbeef")


def test_claim_takes_oldest_available_job_and_starts_a_lease(store):
    _, first = create(store, key="youtube:a", now=NOW)
    create(store, key="youtube:b", now=NOW + timedelta(seconds=1))

    claimed = store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=2))

    assert claimed.id == first.id
    assert claimed.lease_owner == OWNER
    assert claimed.lease_expires_at == NOW + timedelta(seconds=2 + LEASE)
    assert claimed.attempts == 1
    assert store.get_job(first.id) == claimed


def test_claim_skips_leased_future_and_terminal_jobs(store):
    _, leased = create(store, key="youtube:a")
    store.claim_next_job(OWNER, LEASE, NOW)
    _, later = create(store, key="youtube:b")
    store.claim_next_job("other", LEASE, NOW)
    store.schedule_retry(later.id, "other", "boom", NOW + timedelta(minutes=5), NOW)
    _, done = create(store, key="youtube:c")
    complete(store, done.id)

    assert store.claim_next_job("third", LEASE, NOW + timedelta(seconds=1)) is None


def test_expired_lease_can_be_reclaimed_by_another_worker(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    reclaimed = store.claim_next_job("worker-b", LEASE, NOW + timedelta(seconds=LEASE + 1))

    assert reclaimed.id == job.id
    assert reclaimed.lease_owner == "worker-b"
    assert reclaimed.attempts == 2


def test_extend_lease_only_for_current_owner(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    extended = store.extend_lease(job.id, OWNER, LEASE, NOW + timedelta(seconds=60))
    stolen = store.extend_lease(job.id, "intruder", LEASE, NOW + timedelta(seconds=60))

    assert extended is True
    assert stolen is False
    assert store.get_job(job.id).lease_expires_at == NOW + timedelta(seconds=60 + LEASE)


def test_release_lease_makes_job_claimable_immediately(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    store.release_lease(job.id, OWNER, NOW + timedelta(seconds=1))

    released = store.get_job(job.id)
    assert released.lease_owner is None
    assert released.lease_expires_at is None
    assert store.claim_next_job("worker-b", LEASE, NOW + timedelta(seconds=1)).id == job.id


def test_mutations_by_non_owner_raise_lease_lost(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    with pytest.raises(LeaseLostError):
        store.set_job_status(job.id, "intruder", JobStatus.DOWNLOADING, NOW)
    with pytest.raises(LeaseLostError):
        store.commit_stage(job.id, "intruder", JobStatus.DOWNLOADED, [descriptor()], None, NOW)
    with pytest.raises(LeaseLostError):
        store.complete_job(job.id, "intruder", sample_analysis(), NOW)
    with pytest.raises(LeaseLostError):
        store.fail_job(job.id, "intruder", "x", NOW)
    with pytest.raises(LeaseLostError):
        store.schedule_retry(job.id, "intruder", "x", NOW, NOW)


def test_set_job_status_updates_status(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    store.set_job_status(job.id, OWNER, JobStatus.DOWNLOADING, NOW + timedelta(seconds=1))

    updated = store.get_job(job.id)
    assert updated.status == JobStatus.DOWNLOADING
    assert updated.updated_at == NOW + timedelta(seconds=1)


def test_commit_stage_records_artifacts_status_and_cache_atomically(store):
    project, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    drums = descriptor(ArtifactKind.DRUMS_STEM, "projects/p/j/drums.wav")
    accompaniment = descriptor(ArtifactKind.ACCOMPANIMENT_STEM, "projects/p/j/accompaniment.wav")
    entry = CacheEntry(source_key="youtube:abc", stage=Stage.SEPARATE, pipeline_version="1", artifacts=(drums, accompaniment))

    created = store.commit_stage(job.id, OWNER, JobStatus.STEMS_SEPARATED, [drums, accompaniment], entry, NOW)

    assert store.get_job(job.id).status == JobStatus.STEMS_SEPARATED
    by_kind = store.artifacts_for_job(job.id)
    assert set(by_kind) == {ArtifactKind.DRUMS_STEM, ArtifactKind.ACCOMPANIMENT_STEM}
    assert by_kind[ArtifactKind.DRUMS_STEM].storage_key == "projects/p/j/drums.wav"
    assert by_kind[ArtifactKind.DRUMS_STEM].project_id == project.id
    assert by_kind[ArtifactKind.DRUMS_STEM].pruned_at is None
    assert {a.id for a in created} == {a.id for a in by_kind.values()}
    assert store.get_cache_entry("youtube:abc", Stage.SEPARATE, "1") == entry
    assert store.get_cache_entry("youtube:abc", Stage.SEPARATE, "2") is None


def test_commit_stage_failure_leaves_no_partial_state(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    store.claim_next_job("worker-b", LEASE, NOW + timedelta(seconds=LEASE + 1))

    with pytest.raises(LeaseLostError):
        store.commit_stage(job.id, OWNER, JobStatus.DOWNLOADED, [descriptor()], None, NOW)

    assert store.artifacts_for_job(job.id) == {}


def test_fail_job_is_terminal_and_clears_lease(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)

    store.fail_job(job.id, OWNER, "video unavailable", NOW + timedelta(seconds=3))

    failed = store.get_job(job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.error == "video unavailable"
    assert failed.finished_at == NOW + timedelta(seconds=3)
    assert failed.lease_owner is None
    assert store.claim_next_job(OWNER, LEASE, NOW + timedelta(hours=1)) is None


def test_schedule_retry_delays_job_and_keeps_it_non_terminal(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    store.set_job_status(job.id, OWNER, JobStatus.SEPARATING_STEMS, NOW)

    store.schedule_retry(job.id, OWNER, "Unexpected error: oom", NOW + timedelta(seconds=30), NOW)

    retried = store.get_job(job.id)
    assert retried.status == JobStatus.SEPARATING_STEMS
    assert retried.error == "Unexpected error: oom"
    assert retried.lease_owner is None
    assert store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=29)) is None
    assert store.claim_next_job(OWNER, LEASE, NOW + timedelta(seconds=30)).id == job.id


def test_requeue_failed_job_resets_attempts_and_error(store):
    _, job = create(store)
    store.claim_next_job(OWNER, LEASE, NOW)
    store.fail_job(job.id, OWNER, "boom", NOW)

    requeued = store.requeue_failed_job(job.id, NOW + timedelta(minutes=1))

    assert requeued.status == JobStatus.QUEUED
    assert requeued.attempts == 0
    assert requeued.error is None
    assert requeued.finished_at is None
    assert requeued.available_at == NOW + timedelta(minutes=1)


def test_requeue_ignores_non_failed_and_unknown_jobs(store):
    _, job = create(store)

    assert store.requeue_failed_job(job.id, NOW) is None
    assert store.requeue_failed_job("00000000-0000-0000-0000-000000000000", NOW) is None


def run_stage(store, job_id, artifacts, owner=OWNER, now=NOW, cache_entry=None):
    store.claim_next_job(owner, LEASE, now)
    return store.commit_stage(job_id, owner, JobStatus.DOWNLOADED, artifacts, cache_entry, now)


def test_source_audio_of_completed_job_is_disposable_but_stems_are_not(store):
    _, job = create(store)
    run_stage(store, job.id, [descriptor(), descriptor(ArtifactKind.DRUMS_STEM, "k/drums.wav")])
    store.complete_job(job.id, OWNER, sample_analysis(), NOW)

    keys = store.disposable_storage_keys(failed_before=NOW - timedelta(days=7))

    assert keys == {"projects/p/j/source.wav"}


def test_failed_job_artifacts_are_disposable_only_after_retention(store):
    _, job = create(store)
    run_stage(store, job.id, [descriptor(ArtifactKind.DRUMS_STEM, "k/drums.wav")])
    store.fail_job(job.id, OWNER, "boom", NOW)

    assert store.disposable_storage_keys(failed_before=NOW) == set()
    assert store.disposable_storage_keys(failed_before=NOW + timedelta(seconds=1)) == {"k/drums.wav"}


def test_deleted_project_artifacts_are_disposable(store):
    project, job = create(store)
    run_stage(store, job.id, [descriptor(ArtifactKind.DRUMS_STEM, "k/drums.wav")])
    store.soft_delete_project(project.id, NOW)

    assert store.disposable_storage_keys(failed_before=NOW) == {"k/drums.wav"}


def test_key_shared_with_a_live_row_is_not_disposable(store):
    deleted, deleted_job = create(store, key="youtube:abc", now=NOW)
    run_stage(store, deleted_job.id, [descriptor(ArtifactKind.DRUMS_STEM, "shared/drums.wav")])
    store.complete_job(deleted_job.id, OWNER, sample_analysis(), NOW)
    store.soft_delete_project(deleted.id, NOW)
    _, live_job = create(store, key="youtube:abc", now=NOW + timedelta(seconds=1))
    run_stage(store, live_job.id, [descriptor(ArtifactKind.DRUMS_STEM, "shared/drums.wav")], now=NOW + timedelta(seconds=1))

    assert store.disposable_storage_keys(failed_before=NOW + timedelta(days=1)) == set()


def test_mark_pruned_sets_pruned_at_and_drops_referencing_cache_entries(store):
    _, job = create(store)
    source = descriptor()
    entry = CacheEntry(source_key="youtube:abc", stage=Stage.EXTRACT, pipeline_version="1", artifacts=(source,))
    run_stage(store, job.id, [source], cache_entry=entry)

    store.mark_storage_keys_pruned({"projects/p/j/source.wav"}, NOW + timedelta(hours=1))

    artifact = store.artifacts_for_job(job.id)[ArtifactKind.SOURCE_AUDIO]
    assert artifact.pruned_at == NOW + timedelta(hours=1)
    assert store.get_cache_entry("youtube:abc", Stage.EXTRACT, "1") is None
    assert store.disposable_storage_keys(failed_before=NOW + timedelta(days=30)) == set()


def test_mark_pruned_with_no_keys_is_a_no_op(store):
    store.mark_storage_keys_pruned(set(), NOW)


def test_purge_deleted_projects_removes_their_rows(store):
    doomed, doomed_job = create(store, key="youtube:a")
    kept, _ = create(store, key="youtube:b")
    analysis = complete(store, doomed_job.id)
    store.save_score(doomed.id, analysis.id, {"measures": []}, None, NOW)
    store.soft_delete_project(doomed.id, NOW)

    purged = store.purge_deleted_projects()

    assert purged == 1
    assert store.get_project(doomed.id) is None
    assert store.get_job(doomed_job.id) is None
    assert store.latest_analysis(doomed.id) is None
    assert store.latest_score(doomed.id) is None
    assert store.get_project(kept.id) is not None


def test_maintenance_lock_is_exclusive(store):
    with store.maintenance_lock() as first:
        with store.maintenance_lock() as second:
            assert first is True
            assert second is False

    with store.maintenance_lock() as again:
        assert again is True
