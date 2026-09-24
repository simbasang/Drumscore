import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from app.timing import BeatPoint, TempoMap
from app.transcription import DrumEvent


def new_id() -> str:
    return str(uuid.uuid4())


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    SEPARATING_STEMS = "separating_stems"
    STEMS_SEPARATED = "stems_separated"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    MAPPING_TEMPO = "mapping_tempo"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})


class ArtifactKind(str, Enum):
    SOURCE_AUDIO = "source_audio"
    DRUMS_STEM = "drums_stem"
    ACCOMPANIMENT_STEM = "accompaniment_stem"
    RAW_TRANSCRIPTION = "raw_transcription"


class Stage(str, Enum):
    EXTRACT = "extract"
    SEPARATE = "separate"
    TRANSCRIBE = "transcribe"


@dataclass(frozen=True)
class Project:
    id: str
    title: str
    source_kind: str
    source_url: str
    source_key: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class Job:
    id: str
    project_id: str
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error: str | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class NewArtifact:
    kind: ArtifactKind
    storage_key: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Artifact:
    id: str
    project_id: str
    job_id: str
    kind: ArtifactKind
    storage_key: str
    size_bytes: int
    sha256: str
    created_at: datetime
    pruned_at: datetime | None = None


@dataclass(frozen=True)
class CacheEntry:
    source_key: str
    stage: Stage
    pipeline_version: str
    artifacts: tuple[NewArtifact, ...]


@dataclass(frozen=True)
class NewAnalysis:
    pipeline_version: str
    tempo_bpm: float
    tempo_map: TempoMap
    beats: list[BeatPoint]
    events: list[DrumEvent]
    raw_events: list[DrumEvent]


@dataclass(frozen=True)
class Analysis:
    id: str
    project_id: str
    job_id: str
    pipeline_version: str
    tempo_bpm: float
    tempo_map: TempoMap
    beats: list[BeatPoint]
    events: list[DrumEvent]
    raw_events: list[DrumEvent]
    created_at: datetime


@dataclass(frozen=True)
class ScoreVersion:
    id: str
    project_id: str
    analysis_id: str
    version: int
    score: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    latest_job_status: JobStatus | None
    has_edits: bool


class LeaseLostError(Exception):
    """The caller no longer owns the job's lease (another worker reclaimed
    it after expiry), so it must stop touching the job."""


class ScoreVersionConflictError(Exception):
    def __init__(self, latest_version: int | None) -> None:
        super().__init__(f"Score has moved on; latest version is {latest_version}")
        self.latest_version = latest_version
