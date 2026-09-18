import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.jobs import JobStore

DEFAULT_JOB_RETENTION = timedelta(hours=24)


def cleanup_old_jobs(
    store: JobStore,
    storage_dir: Path,
    max_age: timedelta = DEFAULT_JOB_RETENTION,
    now: datetime | None = None,
) -> None:
    cutoff = (now or datetime.now(UTC)) - max_age

    for job in store.list_all():
        if job.created_at >= cutoff:
            continue

        job_dir = storage_dir / job.id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        store.delete(job.id)
