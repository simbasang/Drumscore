import pytest

from app.audio_extraction import AudioExtractionError
from app.job_processor import run_audio_extraction, run_pipeline, run_stem_separation
from app.jobs import JobStatus, JobStore
from app.media_source import ParsedSource
from app.stem_separation import SeparatedStems, StemSeparationError


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


class FakeCrashingExtractor:
    def extract(self, source, destination_dir):
        raise RuntimeError("disk full")


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


def test_run_audio_extraction_marks_job_failed_on_unexpected_exception(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_audio_extraction(job.id, source, store, FakeCrashingExtractor(), tmp_path)

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "disk full" in updated.error


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


class FakeSuccessfulSeparator:
    def separate(self, audio_path, destination_dir):
        return SeparatedStems(
            drums_path=destination_dir / "drums.wav",
            accompaniment_path=destination_dir / "no_drums.wav",
        )


class FakeFailingSeparator:
    def separate(self, audio_path, destination_dir):
        raise StemSeparationError("separation blew up")


class FakeCrashingSeparator:
    def separate(self, audio_path, destination_dir):
        raise RuntimeError("segfault in native code")


def test_run_stem_separation_marks_job_stems_separated_on_success(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_stem_separation(job.id, tmp_path / "source.wav", store, FakeSuccessfulSeparator(), tmp_path)

    updated = store.get(job.id)
    assert updated.status == JobStatus.STEMS_SEPARATED
    assert updated.drums_path == str(tmp_path / "drums.wav")
    assert updated.accompaniment_path == str(tmp_path / "no_drums.wav")


def test_run_stem_separation_marks_job_failed_on_error(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_stem_separation(job.id, tmp_path / "source.wav", store, FakeFailingSeparator(), tmp_path)

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "separation blew up"


def test_run_stem_separation_marks_job_failed_on_unexpected_exception(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_stem_separation(job.id, tmp_path / "source.wav", store, FakeCrashingSeparator(), tmp_path)

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "segfault in native code" in updated.error


def test_run_pipeline_runs_extraction_then_separation_on_success(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_pipeline(
        job.id, source, store, FakeSuccessfulExtractor(), FakeSuccessfulSeparator(), tmp_path
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.STEMS_SEPARATED
    assert updated.audio_path == str(tmp_path / job.id / "source.wav")
    assert updated.drums_path == str(tmp_path / job.id / "drums.wav")


def test_run_pipeline_stops_before_separation_when_extraction_fails(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    separator_called = False

    class SpySeparator:
        def separate(self, audio_path, destination_dir):
            nonlocal separator_called
            separator_called = True
            return SeparatedStems(drums_path=destination_dir / "drums.wav", accompaniment_path=destination_dir / "no_drums.wav")

    run_pipeline(job.id, source, store, FakeFailingExtractor(), SpySeparator(), tmp_path)

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "could not download video"
    assert separator_called is False
