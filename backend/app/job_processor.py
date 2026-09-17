from pathlib import Path

from app.audio_extraction import AudioExtractionError, AudioExtractor
from app.jobs import JobStatus, JobStore
from app.media_source import ParsedSource


def run_audio_extraction(
    job_id: str,
    source: ParsedSource,
    store: JobStore,
    extractor: AudioExtractor,
    storage_dir: Path,
) -> None:
    store.update(job_id, status=JobStatus.DOWNLOADING)

    try:
        audio_path = extractor.extract(source, storage_dir / job_id)
    except AudioExtractionError as error:
        store.update(job_id, status=JobStatus.FAILED, error=str(error))
        return

    store.update(job_id, status=JobStatus.DOWNLOADED, audio_path=str(audio_path))
