from app.config import Settings
from app.demucs_stem_separator import DemucsStemSeparator
from app.drumscript_transcriber import DrumScriptTranscriber
from app.librosa_beat_detector import LibrosaBeatDetector
from app.librosa_tempo_estimator import LibrosaTempoEstimator
from app.persistence.postgres import create_postgres_store
from app.pipeline.runner import PipelineEngines
from app.storage import LocalArtifactStorage
from app.worker.worker import Worker
from app.youtube_audio_extractor import YtDlpAudioExtractor
from app.youtube_source import YouTubeSourceValidator


def default_engines(settings: Settings) -> PipelineEngines:
    return PipelineEngines(
        source_validator=YouTubeSourceValidator(),
        extractor=YtDlpAudioExtractor(
            max_duration_seconds=settings.max_source_duration_seconds,
            max_download_bytes=settings.max_download_bytes,
        ),
        separator=DemucsStemSeparator(),
        transcriber=DrumScriptTranscriber(),
        tempo_estimator=LibrosaTempoEstimator(),
        beat_detector=LibrosaBeatDetector(),
    )


def build_worker(settings: Settings) -> Worker:
    return Worker(
        store=create_postgres_store(settings.database_url.get_secret_value()),
        storage=LocalArtifactStorage(settings.storage_root),
        engines=default_engines(settings),
        settings=settings,
    )
