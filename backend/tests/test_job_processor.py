import pytest

from app.audio_extraction import AudioExtractionError
from app.job_processor import run_audio_extraction
from app.jobs import JobStatus, JobStore
from app.media_source import ParsedSource


@pytest.fixture
def source():
    return ParsedSource(
        url="https://youtu.be/dQw4w9WgXcQ", provider="youtube", external_id="dQw4w9WgXcQ"
    )


class FakeSuccessfulExtractor:
    def extract(self, source, destination_dir):
        return destination_dir / "source.wav"


class FakeFailingExtractor:
    def extract(self, source, destination_dir):
        raise AudioExtractionError("could not download video")


def test_run_audio_extraction_marks_job_downloaded_on_success(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_audio_extraction(job.id, source, store, FakeSuccessfulExtractor(), tmp_path)

    updated = store.get(job.id)
    assert updated.status == JobStatus.DOWNLOADED
    assert updated.audio_path == str(tmp_path / job.id / "source.wav")
    assert updated.error is None


def test_run_audio_extraction_marks_job_failed_on_error(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_audio_extraction(job.id, source, store, FakeFailingExtractor(), tmp_path)

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "could not download video"
    assert updated.audio_path is None


def test_run_audio_extraction_sets_status_to_downloading_while_extracting(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    seen_status = None

    class RecordingExtractor:
        def extract(self, source, destination_dir):
            nonlocal seen_status
            seen_status = store.get(job.id).status
            return destination_dir / "source.wav"

    run_audio_extraction(job.id, source, store, RecordingExtractor(), tmp_path)

    assert seen_status == JobStatus.DOWNLOADING
