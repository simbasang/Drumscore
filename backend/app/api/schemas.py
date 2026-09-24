from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.diagnostics import EventDiagnostic
from app.persistence.models import Job, JobStatus, Project, ProjectSummary
from app.timing import BeatPoint, TempoMap, TempoPoint
from app.transcription import DrumEvent, DrumInstrument


class TempoPointResponse(BaseModel):
    source_time: float
    bpm: float

    @classmethod
    def from_domain(cls, point: TempoPoint) -> "TempoPointResponse":
        return cls(source_time=point.source_time, bpm=point.bpm)


class BeatPointResponse(BaseModel):
    source_time: float
    measure: int
    beat: int
    is_downbeat: bool
    confidence: float | None = None

    @classmethod
    def from_domain(cls, point: BeatPoint) -> "BeatPointResponse":
        return cls(
            source_time=point.source_time,
            measure=point.measure,
            beat=point.beat,
            is_downbeat=point.is_downbeat,
            confidence=point.confidence,
        )


class TempoMapResponse(BaseModel):
    points: list[TempoPointResponse]

    @classmethod
    def from_domain(cls, tempo_map: TempoMap) -> "TempoMapResponse":
        return cls(points=[TempoPointResponse.from_domain(p) for p in tempo_map.points])


class DrumEventResponse(BaseModel):
    id: str
    time: float
    instrument: DrumInstrument
    confidence: float | None = None
    provenance: str | None = None
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None

    @classmethod
    def from_event(cls, event: DrumEvent) -> "DrumEventResponse":
        return cls(
            id=event.id,
            time=event.time,
            instrument=event.instrument,
            confidence=event.confidence,
            provenance=event.provenance,
            measure=event.measure,
            beat=event.beat,
            subdivision=event.subdivision,
        )


class AnalysisResponse(BaseModel):
    tempo_bpm: float
    events: list[DrumEventResponse]
    beats: list[BeatPointResponse] = []


class EventDiagnosticResponse(BaseModel):
    event_id: str
    instrument: DrumInstrument
    source_time: float
    velocity: float | None = None
    confidence: float | None = None
    provenance: str | None = None
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None
    quantized_time: float | None = None
    quantization_error_seconds: float | None = None

    @classmethod
    def from_diagnostic(cls, diagnostic: EventDiagnostic) -> "EventDiagnosticResponse":
        return cls(
            event_id=diagnostic.event_id,
            instrument=diagnostic.instrument,
            source_time=diagnostic.source_time,
            velocity=diagnostic.velocity,
            confidence=diagnostic.confidence,
            provenance=diagnostic.provenance,
            measure=diagnostic.measure,
            beat=diagnostic.beat,
            subdivision=diagnostic.subdivision,
            quantized_time=diagnostic.quantized_time,
            quantization_error_seconds=diagnostic.quantization_error_seconds,
        )


class DiagnosticsResponse(BaseModel):
    tempo_bpm: float
    events: list[EventDiagnosticResponse]


class JobSummaryResponse(BaseModel):
    id: str
    status: JobStatus
    attempts: int
    max_attempts: int
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobSummaryResponse":
        return cls(
            id=job.id,
            status=job.status,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            error=job.error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )


class ProjectResponse(BaseModel):
    id: str
    title: str
    source_url: str
    created_at: datetime
    updated_at: datetime
    latest_job: JobSummaryResponse | None = None

    @classmethod
    def build(cls, project: Project, job: Job | None) -> "ProjectResponse":
        return cls(
            id=project.id,
            title=project.title,
            source_url=project.source_url,
            created_at=project.created_at,
            updated_at=project.updated_at,
            latest_job=JobSummaryResponse.from_job(job) if job else None,
        )


class CreateProjectRequest(BaseModel):
    url: str = Field(max_length=2048)


class CreateProjectResponse(BaseModel):
    project: ProjectResponse
    job: JobSummaryResponse


class DuplicateProjectResponse(BaseModel):
    detail: str
    existing_project_id: str


class ProjectListItemResponse(BaseModel):
    id: str
    title: str
    source_url: str
    updated_at: datetime
    latest_job_status: JobStatus | None = None
    has_edits: bool

    @classmethod
    def from_summary(cls, summary: ProjectSummary) -> "ProjectListItemResponse":
        return cls(
            id=summary.project.id,
            title=summary.project.title,
            source_url=summary.project.source_url,
            updated_at=summary.project.updated_at,
            latest_job_status=summary.latest_job_status,
            has_edits=summary.has_edits,
        )


class SavedScoreResponse(BaseModel):
    version: int
    score: dict[str, Any]


class SaveScoreRequest(BaseModel):
    score: dict[str, Any]
    base_version: int | None = None


class SaveScoreResponse(BaseModel):
    version: int


class ScoreConflictResponse(BaseModel):
    detail: str
    latest_version: int | None = None
