from app.config import Settings
from app.demucs_stem_separator import DemucsStemSeparator
from app.persistence.postgres import PostgresStore
from app.storage import LocalArtifactStorage
from app.worker.factory import build_worker, default_engines
from app.youtube_audio_extractor import YtDlpAudioExtractor


def test_default_engines_use_production_adapters_with_configured_limits():
    settings = Settings(_env_file=None, max_source_duration_seconds=60, max_download_bytes=1000)

    engines = default_engines(settings)

    assert isinstance(engines.extractor, YtDlpAudioExtractor)
    assert engines.extractor.max_duration_seconds == 60
    assert engines.extractor.max_download_bytes == 1000
    assert isinstance(engines.separator, DemucsStemSeparator)


def test_build_worker_wires_postgres_store_and_local_storage(tmp_path):
    settings = Settings(_env_file=None, storage_root=tmp_path, database_url="postgresql+psycopg://u:p@localhost:1/x")

    worker = build_worker(settings)

    assert isinstance(worker.store, PostgresStore)
    assert isinstance(worker.storage, LocalArtifactStorage)
    assert worker.storage.root == tmp_path
