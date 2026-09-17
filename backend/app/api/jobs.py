from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.audio_extraction import AudioExtractor
from app.job_processor import run_audio_extraction
from app.jobs import Job, JobStatus, JobStore
from app.media_source import InvalidSourceUrlError, MediaSourceValidator
from app.youtube_audio_extractor import YtDlpAudioExtractor
from app.youtube_source import YouTubeSourceValidator

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_job_store = JobStore()
_source_validator = YouTubeSourceValidator()
_audio_extractor = YtDlpAudioExtractor()
_storage_dir = Path(__file__).resolve().parent.parent.parent / "data" / "jobs"


def get_job_store() -> JobStore:
    return _job_store


def get_source_validator() -> MediaSourceValidator:
    return _source_validator


def get_audio_extractor() -> AudioExtractor:
    return _audio_extractor


def get_storage_dir() -> Path:
    return _storage_dir


class CreateJobRequest(BaseModel):
    url: str


class JobResponse(BaseModel):
    id: str
    url: str
    status: JobStatus
    audio_path: str | None = None
    error: str | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            url=job.url,
            status=job.status,
            audio_path=job.audio_path,
            error=job.error,
        )


@router.post("", response_model=JobResponse, status_code=201)
def create_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
    store: JobStore = Depends(get_job_store),
    validator: MediaSourceValidator = Depends(get_source_validator),
    extractor: AudioExtractor = Depends(get_audio_extractor),
    storage_dir: Path = Depends(get_storage_dir),
) -> JobResponse:
    try:
        source = validator.parse(request.url)
    except InvalidSourceUrlError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    job = store.create(url=request.url)
    background_tasks.add_task(
        run_audio_extraction, job.id, source, store, extractor, storage_dir
    )
    return JobResponse.from_job(job)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, store: JobStore = Depends(get_job_store)) -> JobResponse:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse.from_job(job)
