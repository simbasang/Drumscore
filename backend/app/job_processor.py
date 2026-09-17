from pathlib import Path

from app.audio_extraction import AudioExtractionError, AudioExtractor
from app.jobs import JobStatus, JobStore
from app.media_source import ParsedSource
from app.stem_separation import StemSeparationError, StemSeparator


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
) -> None:
    store.update(job_id, status=JobStatus.SEPARATING_STEMS)

    try:
        stems = separator.separate(audio_path, destination_dir)
    except StemSeparationError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return
    except Exception as error:  # noqa: BLE001 - guarantee the job reaches a terminal state
        store.update(job_id, status=JobStatus.FAILED, error=f"Unexpected error: {error}")
        return

    store.update(
        job_id,
        status=JobStatus.STEMS_SEPARATED,
        drums_path=str(stems.drums_path),
        accompaniment_path=str(stems.accompaniment_path),
    )


def run_pipeline(
    job_id: str,
    source: ParsedSource,
    store: JobStore,
    extractor: AudioExtractor,
    separator: StemSeparator,
    storage_dir: Path,
) -> None:
    job_dir = storage_dir / job_id
    audio_path = run_audio_extraction(job_id, source, store, extractor, storage_dir)

    if audio_path is None:
        return

    run_stem_separation(job_id, audio_path, store, separator, job_dir)
