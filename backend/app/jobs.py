import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"


@dataclass(frozen=True)
class Job:
    id: str
    url: str
    status: JobStatus
    created_at: datetime


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, url: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            url=url,
            status=JobStatus.QUEUED,
            created_at=datetime.now(UTC),
        )
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
