import pytest

from app.audio_extraction import AudioExtractionError
from app.job_processor import (
    run_audio_extraction,
    run_pipeline,
    run_stem_separation,
    run_tempo_mapping,
    run_transcription,
)
from app.jobs import JobStatus, JobStore
from app.media_source import ParsedSource
from app.stem_separation import SeparatedStems, StemSeparationError
from app.tempo_estimation import TempoEstimationError
from app.transcription import DrumEvent, DrumInstrument, TranscriptionError


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


class FakeSuccessfulTranscriber:
    def transcribe(self, audio_path):
        return [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]


class FakeFailingTranscriber:
    def transcribe(self, audio_path):
        raise TranscriptionError("transcription blew up")


class FakeCrashingTranscriber:
    def transcribe(self, audio_path):
        raise RuntimeError("out of memory")


def test_run_transcription_marks_job_transcribed_on_success(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_transcription(job.id, tmp_path / "drums.wav", store, FakeSuccessfulTranscriber())

    updated = store.get(job.id)
    assert updated.status == JobStatus.TRANSCRIBED
    assert updated.events == [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]


def test_run_transcription_marks_job_failed_on_error(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_transcription(job.id, tmp_path / "drums.wav", store, FakeFailingTranscriber())

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "transcription blew up"


def test_run_transcription_marks_job_failed_on_unexpected_exception(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_transcription(job.id, tmp_path / "drums.wav", store, FakeCrashingTranscriber())

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "out of memory" in updated.error


class FakeSuccessfulTempoEstimator:
    def estimate(self, audio_path):
        return 120.0


class FakeFailingTempoEstimator:
    def estimate(self, audio_path):
        raise TempoEstimationError("could not estimate tempo")


class FakeCrashingTempoEstimator:
    def estimate(self, audio_path):
        raise RuntimeError("division by zero")


def test_run_tempo_mapping_marks_job_tempo_mapped_on_success(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(job.id, tmp_path / "drums.wav", events, store, FakeSuccessfulTempoEstimator())

    updated = store.get(job.id)
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.tempo_bpm == 120.0
    assert updated.events[0].beat == 2
    assert updated.events[0].time == 0.5


def test_run_tempo_mapping_marks_job_failed_on_error(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_tempo_mapping(job.id, tmp_path / "drums.wav", [], store, FakeFailingTempoEstimator())

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "could not estimate tempo"


def test_run_tempo_mapping_marks_job_failed_on_unexpected_exception(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_tempo_mapping(job.id, tmp_path / "drums.wav", [], store, FakeCrashingTempoEstimator())

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "division by zero" in updated.error


def test_run_pipeline_runs_all_four_steps_on_success(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_pipeline(
        job.id,
        source,
        store,
        FakeSuccessfulExtractor(),
        FakeSuccessfulSeparator(),
        FakeSuccessfulTranscriber(),
        FakeSuccessfulTempoEstimator(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.audio_path == str(tmp_path / job.id / "source.wav")
    assert updated.drums_path == str(tmp_path / job.id / "drums.wav")
    assert updated.tempo_bpm == 120.0
    assert updated.events[0].beat is not None


def test_run_pipeline_stops_before_separation_when_extraction_fails(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    separator_called = False

    class SpySeparator:
        def separate(self, audio_path, destination_dir):
            nonlocal separator_called
            separator_called = True
            return SeparatedStems(drums_path=destination_dir / "drums.wav", accompaniment_path=destination_dir / "no_drums.wav")

    run_pipeline(
        job.id,
        source,
        store,
        FakeFailingExtractor(),
        SpySeparator(),
        FakeSuccessfulTranscriber(),
        FakeSuccessfulTempoEstimator(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "could not download video"
    assert separator_called is False


def test_run_pipeline_stops_before_transcription_when_separation_fails(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    transcriber_called = False

    class SpyTranscriber:
        def transcribe(self, audio_path):
            nonlocal transcriber_called
            transcriber_called = True
            return []

    run_pipeline(
        job.id,
        source,
        store,
        FakeSuccessfulExtractor(),
        FakeFailingSeparator(),
        SpyTranscriber(),
        FakeSuccessfulTempoEstimator(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "separation blew up"
    assert transcriber_called is False


def test_run_pipeline_stops_before_tempo_mapping_when_transcription_fails(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    estimator_called = False

    class SpyTempoEstimator:
        def estimate(self, audio_path):
            nonlocal estimator_called
            estimator_called = True
            return 120.0

    run_pipeline(
        job.id,
        source,
        store,
        FakeSuccessfulExtractor(),
        FakeSuccessfulSeparator(),
        FakeFailingTranscriber(),
        SpyTempoEstimator(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "transcription blew up"
    assert estimator_called is False
