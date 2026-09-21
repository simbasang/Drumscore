import dataclasses
import threading
from pathlib import Path
from typing import Callable

from app.audio_extraction import AudioExtractionError, AudioExtractor
from app.beat_detection import BeatDetectionError, BeatDetector
from app.beat_mapping import quantize_events_with_beats
from app.jobs import JobStatus, JobStore
from app.media_source import ParsedSource
from app.stem_separation import StemSeparationError, StemSeparator
from app.tempo_estimation import TempoEstimationError, TempoEstimator
from app.timing import TempoMap
from app.transcription import DrumEvent, DrumTranscriber, TranscriptionError

DEFAULT_MAX_CONCURRENT_PIPELINE_JOBS = 2


class PipelineConcurrencyLimiter:
    """Caps how many pipeline runs execute at once. A job waiting for a
    free slot stays in whatever status it already has (queued, for a new
    job) until the limiter lets it through."""

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT_PIPELINE_JOBS) -> None:
        self._semaphore = threading.BoundedSemaphore(max_concurrent)

    def run(self, func: Callable[..., None], *args: object, **kwargs: object) -> None:
        with self._semaphore:
            func(*args, **kwargs)


def run_audio_extraction(
    job_id: str,
    source: ParsedSource,
    store: JobStore,
    extractor: AudioExtractor,
    storage_dir: Path,
) -> Path | None:
    store.update(job_id, status=JobStatus.DOWNLOADING)

    try:
        audio_path = extractor.extract(source, storage_dir / job_id)
    except AudioExtractionError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return None
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return None

    store.update(job_id, status=JobStatus.DOWNLOADED, audio_path=str(audio_path))
    return audio_path


def run_stem_separation(
    job_id: str,
    audio_path: Path,
    store: JobStore,
    separator: StemSeparator,
    destination_dir: Path,
) -> Path | None:
    store.update(job_id, status=JobStatus.SEPARATING_STEMS)

    try:
        stems = separator.separate(audio_path, destination_dir)
    except StemSeparationError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return None
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return None

    store.update(
        job_id,
        status=JobStatus.STEMS_SEPARATED,
        drums_path=str(stems.drums_path),
        accompaniment_path=str(stems.accompaniment_path),
    )
    return stems.drums_path


def run_transcription(
    job_id: str,
    drums_path: Path,
    store: JobStore,
    transcriber: DrumTranscriber,
) -> list[DrumEvent] | None:
    store.update(job_id, status=JobStatus.TRANSCRIBING)

    try:
        events = transcriber.transcribe(drums_path)
    except TranscriptionError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return None
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return None

    store.update(job_id, status=JobStatus.TRANSCRIBED, events=events, raw_events=events)
    return events


def run_tempo_mapping(
    job_id: str,
    drums_path: Path,
    events: list[DrumEvent],
    store: JobStore,
    tempo_estimator: TempoEstimator,
    beat_detector: BeatDetector,
) -> None:
    store.update(job_id, status=JobStatus.MAPPING_TEMPO)

    try:
        bpm = tempo_estimator.estimate(drums_path)
    except TempoEstimationError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return

    try:
        beats = beat_detector.detect(drums_path)
    except BeatDetectionError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return

    if len(beats) < 2:
        store.update(
            job_id,
            status=JobStatus.FAILED,
            error=f"Beat detection found only {len(beats)} beat(s); tempo mapping requires at least 2",
        )
        return

    quantized_events = quantize_events_with_beats(events, beats)

    # quantize_events_with_beats legitimately produces measure <= 0 for events
    # before the first detected beat point (extrapolated via plain integer
    # arithmetic - documented, unit-tested behavior). The frontend's
    # buildMeasures is 1-based and silently drops any such event, so floor the
    # numbering at 1 with a uniform shift, which preserves relative spacing.
    if quantized_events:
        min_measure = min(event.measure for event in quantized_events)
        if min_measure < 1:
            shift = 1 - min_measure
            quantized_events = [
                dataclasses.replace(event, measure=event.measure + shift)
                for event in quantized_events
            ]

    store.update(
        job_id,
        status=JobStatus.TEMPO_MAPPED,
        tempo_bpm=bpm,
        tempo_map=TempoMap.constant(bpm),
        beats=beats,
        events=quantized_events,
    )


def run_pipeline(
    job_id: str,
    source: ParsedSource,
    store: JobStore,
    extractor: AudioExtractor,
    separator: StemSeparator,
    transcriber: DrumTranscriber,
    tempo_estimator: TempoEstimator,
    beat_detector: BeatDetector,
    storage_dir: Path,
) -> None:
    """Runs each pipeline step in order, skipping any step whose output is
    already present on the job. This lets a retry resume from wherever a
    previous run left off instead of starting over from scratch."""
    job_dir = storage_dir / job_id
    job = store.get(job_id)

    audio_path = Path(job.audio_path) if job.audio_path else None
    if audio_path is None:
        audio_path = run_audio_extraction(job_id, source, store, extractor, storage_dir)
        if audio_path is None:
            return

    drums_path = Path(job.drums_path) if job.drums_path else None
    if drums_path is None:
        drums_path = run_stem_separation(job_id, audio_path, store, separator, job_dir)
        if drums_path is None:
            return

    events = job.events if job.events else None
    if events is None:
        events = run_transcription(job_id, drums_path, store, transcriber)
        if events is None:
            return

    run_tempo_mapping(job_id, drums_path, events, store, tempo_estimator, beat_detector)
