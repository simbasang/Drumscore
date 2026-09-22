import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.audio_extraction import AudioExtractor
from app.beat_detection import BeatDetector
from app.demucs_stem_separator import DemucsStemSeparator
from app.diagnostics import EventDiagnostic, build_event_diagnostics
from app.drumscript_transcriber import DrumScriptTranscriber
from app.job_cleanup import cleanup_old_jobs
from app.job_processor import PipelineConcurrencyLimiter, run_pipeline
from app.jobs import Job, JobStatus, JobStore
from app.librosa_beat_detector import LibrosaBeatDetector
from app.librosa_tempo_estimator import LibrosaTempoEstimator
from app.media_source import InvalidSourceUrlError, MediaSourceValidator
from app.stem_separation import StemSeparator
from app.tempo_estimation import TempoEstimator
from app.timing import BeatPoint, TempoMap, TempoPoint
from app.transcription import DrumEvent, DrumInstrument, DrumTranscriber
from app.youtube_audio_extractor import YtDlpAudioExtractor
from app.youtube_source import YouTubeSourceValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_job_store = JobStore()
_source_validator = YouTubeSourceValidator()
_audio_extractor = YtDlpAudioExtractor()
_stem_separator = DemucsStemSeparator()
_transcriber = DrumScriptTranscriber()
_tempo_estimator = LibrosaTempoEstimator()
_beat_detector = LibrosaBeatDetector()
_storage_dir = Path(__file__).resolve().parent.parent.parent / "data" / "jobs"
_pipeline_limiter = PipelineConcurrencyLimiter()


# These getters are only ever exercised via FastAPI's dependency-injection
# override mechanism in tests, never called directly as themselves.
def get_job_store() -> JobStore:
    return _job_store


def get_source_validator() -> MediaSourceValidator:
    return _source_validator


def get_audio_extractor() -> AudioExtractor:
    return _audio_extractor


def get_stem_separator() -> StemSeparator:
    return _stem_separator


def get_transcriber() -> DrumTranscriber:
    return _transcriber


def get_tempo_estimator() -> TempoEstimator:
    return _tempo_estimator


def get_beat_detector() -> BeatDetector:
    return _beat_detector


def get_storage_dir() -> Path:
    return _storage_dir


def get_pipeline_limiter() -> PipelineConcurrencyLimiter:
    return _pipeline_limiter


class CreateJobRequest(BaseModel):
    url: str


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


class JobResponse(BaseModel):
    id: str
    url: str
    status: JobStatus
    audio_path: str | None = None
    drums_path: str | None = None
    accompaniment_path: str | None = None
    event_count: int | None = None
    tempo_bpm: float | None = None
    tempo_map: TempoMapResponse | None = None
    error: str | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            url=job.url,
            status=job.status,
            audio_path=job.audio_path,
            drums_path=job.drums_path,
            accompaniment_path=job.accompaniment_path,
            event_count=len(job.events) if job.events is not None else None,
            tempo_bpm=job.tempo_bpm,
            tempo_map=TempoMapResponse.from_domain(job.tempo_map) if job.tempo_map else None,
            error=job.error,
        )


@router.post("", response_model=JobResponse, status_code=201)
def create_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_job_store),
    validator: MediaSourceValidator = Depends(get_source_validator),
    extractor: AudioExtractor = Depends(get_audio_extractor),
    separator: StemSeparator = Depends(get_stem_separator),
    transcriber: DrumTranscriber = Depends(get_transcriber),
    tempo_estimator: TempoEstimator = Depends(get_tempo_estimator),
    beat_detector: BeatDetector = Depends(get_beat_detector),
    storage_dir: Path = Depends(get_storage_dir),
    limiter: PipelineConcurrencyLimiter = Depends(get_pipeline_limiter),
) -> JobResponse:
    try:
        source = validator.parse(request.url)
    except InvalidSourceUrlError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    cleanup_old_jobs(store, storage_dir)
    job = store.create(url=request.url)
    background_tasks.add_task(
        limiter.run,
        run_pipeline,
        job.id,
        source,
        store,
        extractor,
        separator,
        transcriber,
        tempo_estimator,
        beat_detector,
        storage_dir,
    )
    return JobResponse.from_job(job)


@router.post("/{job_id}/retry", response_model=JobResponse, status_code=202)
def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_job_store),
    validator: MediaSourceValidator = Depends(get_source_validator),
    extractor: AudioExtractor = Depends(get_audio_extractor),
    separator: StemSeparator = Depends(get_stem_separator),
    transcriber: DrumTranscriber = Depends(get_transcriber),
    tempo_estimator: TempoEstimator = Depends(get_tempo_estimator),
    beat_detector: BeatDetector = Depends(get_beat_detector),
    storage_dir: Path = Depends(get_storage_dir),
    limiter: PipelineConcurrencyLimiter = Depends(get_pipeline_limiter),
) -> JobResponse:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"Only a failed job can be retried; current status is {job.status.value}",
        )

    source = validator.parse(job.url)
    updated = store.update(job_id, status=JobStatus.QUEUED, error=None)
    background_tasks.add_task(
        limiter.run,
        run_pipeline,
        job_id,
        source,
        store,
        extractor,
        separator,
        transcriber,
        tempo_estimator,
        beat_detector,
        storage_dir,
    )
    return JobResponse.from_job(updated)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, store: JobStore = Depends(get_job_store)) -> JobResponse:
    job = store.get(job_id)

    if job is None:
        logger.warning("Job status requested for unknown job %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse.from_job(job)


@router.get("/{job_id}/audio/drums")
def get_job_drums_audio(job_id: str, store: JobStore = Depends(get_job_store)) -> FileResponse:
    job = store.get(job_id)

    if job is None:
        logger.warning("Drum audio requested for unknown job %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")

    if job.drums_path is None:
        logger.warning(
            "Drum audio requested for job %s before it was ready (status=%s)",
            job_id,
            job.status.value,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Drum audio not available yet: job status is {job.status.value}",
        )

    logger.info("Serving drum audio for job %s from %s", job_id, job.drums_path)
    return FileResponse(job.drums_path, media_type="audio/wav")


@router.get("/{job_id}/audio/accompaniment")
def get_job_accompaniment_audio(
    job_id: str, store: JobStore = Depends(get_job_store)
) -> FileResponse:
    job = store.get(job_id)

    if job is None:
        logger.warning("Accompaniment audio requested for unknown job %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")

    if job.accompaniment_path is None:
        logger.warning(
            "Accompaniment audio requested for job %s before it was ready (status=%s)",
            job_id,
            job.status.value,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Accompaniment audio not available yet: job status is {job.status.value}",
        )

    logger.info("Serving accompaniment audio for job %s from %s", job_id, job.accompaniment_path)
    return FileResponse(job.accompaniment_path, media_type="audio/wav")


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


@router.get("/{job_id}/analysis", response_model=AnalysisResponse)
def get_job_analysis(job_id: str, store: JobStore = Depends(get_job_store)) -> AnalysisResponse:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.events is None or job.tempo_bpm is None:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis not available yet: job status is {job.status.value}",
        )

    return AnalysisResponse(
        tempo_bpm=job.tempo_bpm,
        events=[DrumEventResponse.from_event(event) for event in job.events],
    )


class EventDiagnosticResponse(BaseModel):
    event_id: str
    instrument: DrumInstrument
    source_time: float
    velocity: float | None = None
    confidence: float | None = None
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
            measure=diagnostic.measure,
            beat=diagnostic.beat,
            subdivision=diagnostic.subdivision,
            quantized_time=diagnostic.quantized_time,
            quantization_error_seconds=diagnostic.quantization_error_seconds,
        )


class DiagnosticsResponse(BaseModel):
    tempo_bpm: float
    events: list[EventDiagnosticResponse]


@router.get("/{job_id}/diagnostics", response_model=DiagnosticsResponse)
def get_job_diagnostics(
    job_id: str, store: JobStore = Depends(get_job_store)
) -> DiagnosticsResponse:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if (
        job.raw_events is None
        or job.events is None
        or job.tempo_bpm is None
        or job.beats is None
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Diagnostics not available yet: job status is {job.status.value}",
        )

    diagnostics = build_event_diagnostics(job.raw_events, job.events, job.tempo_bpm, beats=job.beats)
    return DiagnosticsResponse(
        tempo_bpm=job.tempo_bpm,
        events=[EventDiagnosticResponse.from_diagnostic(d) for d in diagnostics],
    )
