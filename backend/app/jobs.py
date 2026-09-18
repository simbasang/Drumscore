import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from app.transcription import DrumEvent


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    SEPARATING_STEMS = "separating_stems"
    STEMS_SEPARATED = "stems_separated"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    FAILED = "failed"


@dataclass(frozen=True)
class Job:
    id: str
    url: str
    status: JobStatus
    created_at: datetime
    audio_path: str | None = None
    drums_path: str | None = None
    accompaniment_path: str | None = None
    events: list[DrumEvent] | None = None
    error: str | None = None


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

    def update(self, job_id: str, **changes: object) -> Job:
        current = self._jobs[job_id]
        updated = dataclasses.replace(current, **changes)
        self._jobs[job_id] = updated
        return updated
