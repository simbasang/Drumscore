from datetime import UTC, datetime, timedelta

from app.job_cleanup import DEFAULT_JOB_RETENTION, cleanup_old_jobs
from app.jobs import JobStore


def test_cleanup_removes_jobs_and_their_files_older_than_the_retention_window(tmp_path):
    store = JobStore()
    old_job = store.create(url="https://youtu.be/aaaaaaaaaaa")
    old_job_dir = tmp_path / old_job.id
    old_job_dir.mkdir()
    (old_job_dir / "source.wav").write_bytes(b"data")
    now = datetime.now(UTC)
    store.update(old_job.id, created_at=now - timedelta(hours=48))

    cleanup_old_jobs(store, tmp_path, max_age=timedelta(hours=24), now=now)

    assert store.get(old_job.id) is None
    assert not old_job_dir.exists()


def test_cleanup_keeps_jobs_within_the_retention_window(tmp_path):
    store = JobStore()
    recent_job = store.create(url="https://youtu.be/aaaaaaaaaaa")
    recent_job_dir = tmp_path / recent_job.id
    recent_job_dir.mkdir()
    now = datetime.now(UTC)
    store.update(recent_job.id, created_at=now - timedelta(hours=1))

    cleanup_old_jobs(store, tmp_path, max_age=timedelta(hours=24), now=now)

    assert store.get(recent_job.id) is not None
    assert recent_job_dir.exists()


def test_cleanup_tolerates_a_job_with_no_files_on_disk(tmp_path):
    store = JobStore()
    old_job = store.create(url="https://youtu.be/aaaaaaaaaaa")
    now = datetime.now(UTC)
    store.update(old_job.id, created_at=now - timedelta(hours=48))

    cleanup_old_jobs(store, tmp_path, max_age=timedelta(hours=24), now=now)

    assert store.get(old_job.id) is None


def test_default_retention_is_24_hours():
    assert DEFAULT_JOB_RETENTION == timedelta(hours=24)
