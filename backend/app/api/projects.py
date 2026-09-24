import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse

from app.api.schemas import (
    AnalysisResponse,
    BeatPointResponse,
    CreateProjectRequest,
    CreateProjectResponse,
    DiagnosticsResponse,
    DrumEventResponse,
    DuplicateProjectResponse,
    EventDiagnosticResponse,
    JobSummaryResponse,
    ProjectListItemResponse,
    ProjectResponse,
    SavedScoreResponse,
    SaveScoreRequest,
    SaveScoreResponse,
    ScoreConflictResponse,
)
from app.clock import utc_now
from app.config import Settings, get_settings
from app.diagnostics import build_event_diagnostics
from app.media_source import InvalidSourceUrlError, MediaSourceValidator
from app.persistence.models import Analysis, ArtifactKind, JobStatus, Project, ScoreVersionConflictError
from app.persistence.postgres import create_postgres_store
from app.persistence.store import Store
from app.storage import ArtifactStorage, LocalArtifactStorage
from app.youtube_source import YouTubeSourceValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

_STEM_KINDS = {"drums": ArtifactKind.DRUMS_STEM, "accompaniment": ArtifactKind.ACCOMPANIMENT_STEM}


# The getters below are the production wiring. Tests replace every one of
# them through app.dependency_overrides, so their bodies only run in the
# real server.
@lru_cache
def get_store() -> Store:  # pragma: no cover - production wiring, overridden in tests
    return create_postgres_store(get_settings().database_url)


@lru_cache
def get_storage() -> ArtifactStorage:  # pragma: no cover - production wiring, overridden in tests
    return LocalArtifactStorage(get_settings().storage_root)


def get_source_validator() -> MediaSourceValidator:  # pragma: no cover - production wiring, overridden in tests
    return YouTubeSourceValidator()


def get_clock() -> Callable[[], datetime]:  # pragma: no cover - production wiring, overridden in tests
    return utc_now


def get_app_settings() -> Settings:  # pragma: no cover - production wiring, overridden in tests
    return get_settings()


def _live_project(store: Store, project_id: str) -> Project:
    """Every project route resolves its id here. An id that is not a UUID
    cannot name a project, so it is a 404 like any unknown id (and never
    reaches the database's uuid column)."""
    not_found = HTTPException(status_code=404, detail="Project not found")
    try:
        canonical_id = str(uuid.UUID(project_id))
    except ValueError as error:
        raise not_found from error
    project = store.get_project(canonical_id)
    if project is None or project.deleted_at is not None:
        raise not_found
    return project


def _require_analysis(store: Store, project: Project, what: str) -> Analysis:
    analysis = store.latest_analysis(project.id)
    if analysis is None:
        job = store.latest_job(project.id)
        status = job.status.value if job else "unknown"
        raise HTTPException(status_code=409, detail=f"{what} not available yet: job status is {status}")
    return analysis


@router.post("", status_code=201, response_model=CreateProjectResponse, responses={409: {"model": DuplicateProjectResponse}})
def create_project(
    request: CreateProjectRequest,
    force: bool = False,
    store: Store = Depends(get_store),
    validator: MediaSourceValidator = Depends(get_source_validator),
    settings: Settings = Depends(get_app_settings),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    url = request.url.strip()
    try:
        source = validator.parse(url)
    except InvalidSourceUrlError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    source_key = f"{source.provider}:{source.external_id}"
    existing = store.find_live_project_by_source_key(source_key)
    if existing is not None and not force:
        return JSONResponse(
            status_code=409,
            content={"detail": "A project for this song already exists", "existing_project_id": existing.id},
        )

    project, job = store.create_project_with_job(
        source_kind=source.provider,
        source_url=url,
        source_key=source_key,
        title=existing.title if existing else url,
        max_attempts=settings.max_attempts,
        now=clock(),
    )
    logger.info("Created project %s (job %s, correlation %s)", project.id, job.id, job.correlation_id)
    return CreateProjectResponse(project=ProjectResponse.build(project, job), job=JobSummaryResponse.from_job(job))


@router.get("", response_model=list[ProjectListItemResponse])
def list_projects(store: Store = Depends(get_store)) -> list[ProjectListItemResponse]:
    return [ProjectListItemResponse.from_summary(summary) for summary in store.list_live_projects()]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, store: Store = Depends(get_store)) -> ProjectResponse:
    project = _live_project(store, project_id)
    return ProjectResponse.build(project, store.latest_job(project.id))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, store: Store = Depends(get_store), clock: Callable[[], datetime] = Depends(get_clock)
) -> Response:
    project = _live_project(store, project_id)
    store.soft_delete_project(project.id, clock())
    return Response(status_code=204)


@router.post("/{project_id}/retry", status_code=202, response_model=JobSummaryResponse)
def retry_project(
    project_id: str, store: Store = Depends(get_store), clock: Callable[[], datetime] = Depends(get_clock)
) -> JobSummaryResponse:
    project = _live_project(store, project_id)
    job = store.latest_job(project.id)
    if job is None or job.status != JobStatus.FAILED:
        status = job.status.value if job else "unknown"
        raise HTTPException(status_code=409, detail=f"Only a failed job can be retried; current status is {status}")
    requeued = store.requeue_failed_job(job.id, clock())
    if requeued is None:
        # Another request requeued (or otherwise changed) the job between the
        # status check above and the conditional requeue.
        raise HTTPException(
            status_code=409, detail="Only a failed job can be retried; it was requeued or changed meanwhile"
        )
    return JobSummaryResponse.from_job(requeued)


@router.get("/{project_id}/analysis", response_model=AnalysisResponse)
def get_analysis(project_id: str, store: Store = Depends(get_store)) -> AnalysisResponse:
    analysis = _require_analysis(store, _live_project(store, project_id), "Analysis")
    return AnalysisResponse(
        tempo_bpm=analysis.tempo_bpm,
        events=[DrumEventResponse.from_event(event) for event in analysis.events],
        beats=[BeatPointResponse.from_domain(beat) for beat in analysis.beats],
    )


@router.get("/{project_id}/diagnostics", response_model=DiagnosticsResponse)
def get_diagnostics(project_id: str, store: Store = Depends(get_store)) -> DiagnosticsResponse:
    analysis = _require_analysis(store, _live_project(store, project_id), "Diagnostics")
    diagnostics = build_event_diagnostics(analysis.raw_events, analysis.events, analysis.tempo_bpm, beats=analysis.beats)
    return DiagnosticsResponse(
        tempo_bpm=analysis.tempo_bpm,
        events=[EventDiagnosticResponse.from_diagnostic(d) for d in diagnostics],
    )


@router.get("/{project_id}/audio/{stem}")
def get_audio(
    project_id: str,
    stem: Literal["drums", "accompaniment"],
    store: Store = Depends(get_store),
    storage: ArtifactStorage = Depends(get_storage),
) -> FileResponse:
    analysis = _require_analysis(store, _live_project(store, project_id), "Audio")
    artifact = store.artifacts_for_job(analysis.job_id).get(_STEM_KINDS[stem])
    if artifact is None:
        raise HTTPException(status_code=409, detail="Audio not available yet")
    if artifact.pruned_at is not None or not storage.exists(artifact.storage_key):
        raise HTTPException(status_code=410, detail="Audio has been removed; re-process the project")
    return FileResponse(storage.path(artifact.storage_key), media_type="audio/wav")


@router.get("/{project_id}/score", response_model=SavedScoreResponse)
def get_score(project_id: str, store: Store = Depends(get_store)) -> SavedScoreResponse:
    project = _live_project(store, project_id)
    saved = store.latest_score(project.id)
    if saved is None:
        raise HTTPException(status_code=404, detail="No saved score for this project")
    return SavedScoreResponse(version=saved.version, score=saved.score)


@router.put("/{project_id}/score", status_code=201, response_model=SaveScoreResponse, responses={409: {"model": ScoreConflictResponse}})
def save_score(
    project_id: str,
    request: SaveScoreRequest,
    store: Store = Depends(get_store),
    clock: Callable[[], datetime] = Depends(get_clock),
):
    project = _live_project(store, project_id)
    if not isinstance(request.score.get("measures"), list):
        raise HTTPException(status_code=422, detail="Invalid score: expected an object with a measures array")
    analysis = _require_analysis(store, project, "Score saving")
    try:
        saved = store.save_score(project.id, analysis.id, request.score, request.base_version, clock())
    except ScoreVersionConflictError as conflict:
        return JSONResponse(
            status_code=409,
            content={"detail": "A newer version of this score was saved elsewhere", "latest_version": conflict.latest_version},
        )
    return SaveScoreResponse(version=saved.version)
