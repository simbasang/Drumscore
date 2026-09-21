from app.jobs import JobStatus, JobStore
from app.transcription import DrumEvent, DrumInstrument


def test_create_assigns_unique_id_and_queued_status():
    store = JobStore()

    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    assert job.url == "https://youtu.be/dQw4w9WgXcQ"
    assert job.status == JobStatus.QUEUED
    assert job.id


def test_create_assigns_different_ids_to_different_jobs():
    store = JobStore()

    first = store.create(url="https://youtu.be/aaaaaaaaaaa")
    second = store.create(url="https://youtu.be/bbbbbbbbbbb")

    assert first.id != second.id


def test_get_returns_previously_created_job():
    store = JobStore()
    created = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    found = store.get(created.id)

    assert found == created


def test_get_returns_none_for_unknown_id():
    store = JobStore()

    found = store.get("does-not-exist")

    assert found is None


def test_update_changes_status_and_returns_updated_job():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    updated = store.update(job.id, status=JobStatus.DOWNLOADING)

    assert updated.status == JobStatus.DOWNLOADING
    assert store.get(job.id).status == JobStatus.DOWNLOADING


def test_update_sets_audio_path_on_success():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    updated = store.update(job.id, status=JobStatus.DOWNLOADED, audio_path="/data/source.wav")

    assert updated.status == JobStatus.DOWNLOADED
    assert updated.audio_path == "/data/source.wav"


def test_update_sets_error_on_failure():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    updated = store.update(job.id, status=JobStatus.FAILED, error="boom")

    assert updated.status == JobStatus.FAILED
    assert updated.error == "boom"


def test_update_sets_events_on_transcription_success():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")
    events = [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]

    updated = store.update(job.id, status=JobStatus.TRANSCRIBED, events=events)

    assert updated.status == JobStatus.TRANSCRIBED
    assert updated.events == events


def test_update_sets_tempo_on_mapping_success():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    updated = store.update(job.id, status=JobStatus.TEMPO_MAPPED, tempo_bpm=128.5)

    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.tempo_bpm == 128.5


def test_update_sets_stem_paths_on_separation_success():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    updated = store.update(
        job.id,
        status=JobStatus.STEMS_SEPARATED,
        drums_path="/data/drums.wav",
        accompaniment_path="/data/no_drums.wav",
    )

    assert updated.status == JobStatus.STEMS_SEPARATED
    assert updated.drums_path == "/data/drums.wav"
    assert updated.accompaniment_path == "/data/no_drums.wav"


def test_list_all_returns_every_created_job():
    store = JobStore()
    first = store.create(url="https://youtu.be/aaaaaaaaaaa")
    second = store.create(url="https://youtu.be/bbbbbbbbbbb")

    result = store.list_all()

    assert {job.id for job in result} == {first.id, second.id}


def test_list_all_returns_empty_list_when_no_jobs_exist():
    store = JobStore()

    assert store.list_all() == []


def test_delete_removes_a_job():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    store.delete(job.id)

    assert store.get(job.id) is None


def test_delete_is_a_noop_for_an_unknown_job():
    store = JobStore()

    store.delete("does-not-exist")


from app.timing import BeatPoint


def test_job_beats_defaults_to_none():
    store = JobStore()

    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")

    assert job.beats is None


def test_update_can_set_beats():
    store = JobStore()
    job = store.create(url="https://youtu.be/dQw4w9WgXcQ")
    beats = [
        BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True),
        BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False),
    ]

    updated = store.update(job.id, beats=beats)

    assert updated.beats == beats
    assert store.get(job.id).beats == beats
