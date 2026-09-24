import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from app.audio_extraction import AudioExtractor
from app.beat_detection import BeatDetector
from app.media_source import MediaSourceValidator
from app.observability.logging import log_event
from app.observability.redaction import sanitize_error_message
from app.persistence.models import (
    Artifact,
    ArtifactKind,
    CacheEntry,
    Job,
    JobStatus,
    LeaseLostError,
    NewAnalysis,
    NewArtifact,
    Project,
    Stage,
)
from app.persistence.serialization import events_from_json_bytes, events_to_json_bytes
from app.persistence.store import Store
from app.pipeline.errors import backoff_seconds, is_permanent
from app.pipeline.tempo_mapping import map_tempo
from app.pipeline.version import PIPELINE_VERSION
from app.stem_separation import StemSeparator
from app.storage import ArtifactStorage, artifact_key
from app.tempo_estimation import TempoEstimator
from app.transcription import DrumTranscriber

logger = logging.getLogger(__name__)

_FILENAMES = {
    ArtifactKind.SOURCE_AUDIO: "source.wav",
    ArtifactKind.DRUMS_STEM: "drums.wav",
    ArtifactKind.ACCOMPANIMENT_STEM: "accompaniment.wav",
    ArtifactKind.RAW_TRANSCRIPTION: "raw_transcription.json",
}

StageOutputs = list[tuple[ArtifactKind, Path]]

JobOutcome = Literal["completed", "failed", "retry_scheduled"]


@dataclass(frozen=True)
class PipelineEngines:
    source_validator: MediaSourceValidator
    extractor: AudioExtractor
    separator: StemSeparator
    transcriber: DrumTranscriber
    tempo_estimator: TempoEstimator
    beat_detector: BeatDetector


@dataclass(frozen=True)
class JobContext:
    store: Store
    storage: ArtifactStorage
    engines: PipelineEngines
    owner: str
    retry_base_seconds: int
    clock: Callable[[], datetime]
    should_stop: Callable[[], bool] = field(default=lambda: False)
    error_roots: tuple[tuple[Path, str], ...] = ()
    monotonic: Callable[[], float] = time.monotonic


class JobAbandoned(Exception):
    """Raised between stages when the worker is stopping or has lost its
    lease, or when a stage fails after a stop was requested; committed
    stages stay, the rest resumes on the next claim."""


def process_job(job: Job, ctx: JobContext) -> JobOutcome:
    """Runs every stage that has no committed output yet, then maps tempo
    and completes the job. Idempotent: each stage's output is written to
    storage and committed (with its cache entry and status) before the
    next stage starts, so re-running after any crash only redoes the stage
    that was in flight. Returns how the attempt ended; abandonment and
    lease loss are raised instead."""
    project = ctx.store.get_project(job.project_id)
    if project is None or project.deleted_at is not None:
        ctx.store.fail_job(job.id, ctx.owner, "Project was deleted", ctx.clock())
        return "failed"

    try:
        _run_stages(job, project, ctx)
    except (JobAbandoned, LeaseLostError):
        raise
    except Exception as error:  # noqa: BLE001 - every failure must end in fail, retry or abandon
        if ctx.should_stop():
            # A stop (or lost lease) was already requested, so the error is
            # most likely the stop itself (an engine child or yt-dlp's ffmpeg
            # killed by the same signal) and says nothing about the input.
            logger.info("Job %s: stage ended with %r after a stop request; abandoning", job.id, error)
            raise JobAbandoned(job.id) from error
        return _handle_failure(job, ctx, error)
    return "completed"


def _handle_failure(job: Job, ctx: JobContext, error: Exception) -> JobOutcome:
    now = ctx.clock()
    if is_permanent(error):
        logger.info("Job %s failed permanently: %s", job.id, error)
        ctx.store.fail_job(job.id, ctx.owner, sanitize_error_message(str(error), ctx.error_roots), now)
        return "failed"

    message = sanitize_error_message(f"Unexpected error: {error}", ctx.error_roots)
    logger.exception("Job %s crashed on attempt %d/%d", job.id, job.attempts, job.max_attempts)
    if job.attempts >= job.max_attempts:
        ctx.store.fail_job(job.id, ctx.owner, message, now)
        return "failed"
    delay = backoff_seconds(job.attempts, ctx.retry_base_seconds)
    ctx.store.schedule_retry(job.id, ctx.owner, message, now + timedelta(seconds=delay), now)
    return "retry_scheduled"


def _elapsed_ms(started: float, ctx: JobContext) -> int:
    return round((ctx.monotonic() - started) * 1000)


@contextmanager
def _timed_stage(stage: str, ctx: JobContext) -> Iterator[None]:
    started = ctx.monotonic()
    log_event(logger, "stage_started", stage=stage)
    try:
        yield
    except LeaseLostError:
        raise
    except Exception as error:
        log_event(
            logger, "stage_failed", logging.WARNING,
            stage=stage, duration_ms=_elapsed_ms(started, ctx),
            error_type=type(error).__name__, permanent=is_permanent(error),
        )
        raise
    log_event(logger, "stage_finished", stage=stage, duration_ms=_elapsed_ms(started, ctx), outcome="ran")


def _checkpoint(job: Job, ctx: JobContext) -> None:
    if ctx.should_stop():
        raise JobAbandoned(job.id)


def _live_artifacts(job: Job, ctx: JobContext) -> dict[ArtifactKind, Artifact]:
    return {
        kind: artifact
        for kind, artifact in ctx.store.artifacts_for_job(job.id).items()
        if artifact.pruned_at is None and ctx.storage.exists(artifact.storage_key)
    }


def _run_stages(job: Job, project: Project, ctx: JobContext) -> None:
    artifacts = _live_artifacts(job, ctx)

    if not {ArtifactKind.DRUMS_STEM, ArtifactKind.ACCOMPANIMENT_STEM} <= artifacts.keys():
        # Cached stems make the source audio unnecessary (the pruner removes
        # it once a job completes), so only extract when separation will run.
        if ArtifactKind.SOURCE_AUDIO not in artifacts and _usable_cache_entry(Stage.SEPARATE, project, ctx) is None:
            artifacts |= _obtain(
                Stage.EXTRACT, job, project, ctx, JobStatus.DOWNLOADING, JobStatus.DOWNLOADED,
                lambda staging: _extract(project, ctx, staging),
            )
            _checkpoint(job, ctx)
        artifacts |= _obtain(
            Stage.SEPARATE, job, project, ctx, JobStatus.SEPARATING_STEMS, JobStatus.STEMS_SEPARATED,
            lambda staging: _separate(artifacts[ArtifactKind.SOURCE_AUDIO], ctx, staging),
        )
        _checkpoint(job, ctx)

    if ArtifactKind.RAW_TRANSCRIPTION not in artifacts:
        artifacts |= _obtain(
            Stage.TRANSCRIBE, job, project, ctx, JobStatus.TRANSCRIBING, JobStatus.TRANSCRIBED,
            lambda staging: _transcribe(artifacts[ArtifactKind.DRUMS_STEM], ctx, staging),
        )
        _checkpoint(job, ctx)

    _map_tempo_and_complete(job, artifacts, ctx)


def _obtain(
    stage: Stage,
    job: Job,
    project: Project,
    ctx: JobContext,
    running: JobStatus,
    done: JobStatus,
    produce: Callable[[Path], StageOutputs],
) -> dict[ArtifactKind, Artifact]:
    cached = _usable_cache_entry(stage, project, ctx)
    if cached is not None:
        started = ctx.monotonic()
        created = ctx.store.commit_stage(job.id, ctx.owner, done, cached.artifacts, None, ctx.clock())
        log_event(logger, "stage_finished", stage=stage.value, duration_ms=_elapsed_ms(started, ctx), outcome="cached")
        return {artifact.kind: artifact for artifact in created}

    with _timed_stage(stage.value, ctx):
        ctx.store.set_job_status(job.id, ctx.owner, running, ctx.clock())
        with ctx.storage.staging_dir() as staging:
            descriptors = tuple(_store_output(job, kind, path, ctx) for kind, path in produce(staging))
        entry = CacheEntry(source_key=project.source_key, stage=stage, pipeline_version=PIPELINE_VERSION, artifacts=descriptors)
        created = ctx.store.commit_stage(job.id, ctx.owner, done, descriptors, entry, ctx.clock())
    return {artifact.kind: artifact for artifact in created}


def _usable_cache_entry(stage: Stage, project: Project, ctx: JobContext) -> CacheEntry | None:
    cached = ctx.store.get_cache_entry(project.source_key, stage, PIPELINE_VERSION)
    if cached is not None and all(ctx.storage.exists(a.storage_key) for a in cached.artifacts):
        return cached
    return None


def _store_output(job: Job, kind: ArtifactKind, path: Path, ctx: JobContext) -> NewArtifact:
    stored = ctx.storage.put(artifact_key(job.project_id, job.id, _FILENAMES[kind]), path)
    return NewArtifact(kind=kind, storage_key=stored.key, size_bytes=stored.size_bytes, sha256=stored.sha256)


def _extract(project: Project, ctx: JobContext, staging: Path) -> StageOutputs:
    source = ctx.engines.source_validator.parse(project.source_url)
    result = ctx.engines.extractor.extract(source, staging)
    if result.title and project.title == project.source_url:
        ctx.store.set_project_title(project.id, result.title, ctx.clock())
    return [(ArtifactKind.SOURCE_AUDIO, result.audio_path)]


def _separate(source_audio: Artifact, ctx: JobContext, staging: Path) -> StageOutputs:
    stems = ctx.engines.separator.separate(ctx.storage.path(source_audio.storage_key), staging)
    return [(ArtifactKind.DRUMS_STEM, stems.drums_path), (ArtifactKind.ACCOMPANIMENT_STEM, stems.accompaniment_path)]


def _transcribe(drums: Artifact, ctx: JobContext, staging: Path) -> StageOutputs:
    events = ctx.engines.transcriber.transcribe(ctx.storage.path(drums.storage_key))
    output = staging / "raw_transcription.json"
    output.write_bytes(events_to_json_bytes(events))
    return [(ArtifactKind.RAW_TRANSCRIPTION, output)]


def _map_tempo_and_complete(job: Job, artifacts: dict[ArtifactKind, Artifact], ctx: JobContext) -> None:
    with _timed_stage("map_tempo", ctx):
        ctx.store.set_job_status(job.id, ctx.owner, JobStatus.MAPPING_TEMPO, ctx.clock())
        raw_events = events_from_json_bytes(ctx.storage.read_bytes(artifacts[ArtifactKind.RAW_TRANSCRIPTION].storage_key))
        drums_path = ctx.storage.path(artifacts[ArtifactKind.DRUMS_STEM].storage_key)
        result = map_tempo(drums_path, raw_events, ctx.engines.tempo_estimator, ctx.engines.beat_detector)
        ctx.store.complete_job(
            job.id,
            ctx.owner,
            NewAnalysis(
                pipeline_version=PIPELINE_VERSION,
                tempo_bpm=result.tempo_bpm,
                tempo_map=result.tempo_map,
                beats=result.beats,
                events=result.events,
                raw_events=raw_events,
            ),
            ctx.clock(),
        )
