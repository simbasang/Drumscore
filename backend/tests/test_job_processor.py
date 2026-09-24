import threading
import time

import pytest

from app.audio_extraction import AudioExtractionError, ExtractedAudio
from app.beat_detection import BeatDetectionError
from app.job_processor import (
    PipelineConcurrencyLimiter,
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
from app.timing import BeatPoint, TempoPoint
from app.transcription import DrumEvent, DrumInstrument, TranscriptionError


@pytest.fixture
def source():
    return ParsedSource(
        url="https://youtu.be/dQw4w9WgXcQ", provider="youtube", external_id="dQw4w9WgXcQ"
    )


class FakeSuccessfulExtractor:
    def extract(self, source, destination_dir):
        return ExtractedAudio(destination_dir / "source.wav")


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


class FakeSuccessfulBeatDetector:
    def detect(self, audio_path):
        return [
            BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True),
            BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False),
            BeatPoint(source_time=1.0, measure=1, beat=3, is_downbeat=False),
            BeatPoint(source_time=1.5, measure=1, beat=4, is_downbeat=False),
        ]


class FakeOffsetBeatDetector:
    """Beats whose first point is NOT at t=0 - the scenario that
    distinguishes beat-anchored quantization from the legacy t=0 grid."""

    def detect(self, audio_path):
        return [
            BeatPoint(source_time=2.5, measure=1, beat=1, is_downbeat=True),
            BeatPoint(source_time=3.0, measure=1, beat=2, is_downbeat=False),
            BeatPoint(source_time=3.5, measure=1, beat=3, is_downbeat=False),
        ]


class FakeSingleBeatDetector:
    def detect(self, audio_path):
        return [BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True)]


class FakeFailingBeatDetector:
    def detect(self, audio_path):
        raise BeatDetectionError("no onsets detected")


class FakeCrashingBeatDetector:
    def detect(self, audio_path):
        raise RuntimeError("native decode failure")


def test_run_tempo_mapping_marks_job_tempo_mapped_on_success(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.tempo_bpm == 120.0
    assert updated.events[0].beat == 2
    assert updated.events[0].time == 0.5


def test_run_tempo_mapping_populates_tempo_map_alongside_tempo_bpm(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.tempo_bpm == 120.0
    assert updated.tempo_map is not None
    assert updated.tempo_map.bpm_at(0.0) == 120.0
    assert updated.tempo_map.points == (TempoPoint(source_time=0.0, bpm=120.0),)


def test_run_tempo_mapping_marks_job_failed_on_error(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        [],
        store,
        FakeFailingTempoEstimator(),
        FakeSuccessfulBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "could not estimate tempo"


def test_run_tempo_mapping_marks_job_failed_on_unexpected_exception(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        [],
        store,
        FakeCrashingTempoEstimator(),
        FakeSuccessfulBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "division by zero" in updated.error


def test_run_tempo_mapping_quantizes_with_beats_and_stores_them(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeOffsetBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.beats == FakeOffsetBeatDetector().detect(None)
    # The whole point of beat-anchoring: an event exactly at the first real
    # beat's time (2.5s, not 0s) quantizes to beat 1 - the legacy t=0 grid
    # would instead have placed 2.5s deep into several earlier measures.
    assert updated.events[0].measure == 1
    assert updated.events[0].beat == 1
    assert updated.events[0].subdivision == 0
    assert updated.events[0].time == 2.5


def test_run_tempo_mapping_marks_job_failed_when_beat_detection_fails(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeFailingBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "no onsets detected"


def test_run_tempo_mapping_marks_job_failed_when_fewer_than_two_beats_detected(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeSingleBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "Beat detection found only 1 beat(s); tempo mapping requires at least 2"


def test_run_tempo_mapping_marks_job_failed_on_unexpected_beat_detector_exception(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeCrashingBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert "native decode failure" in updated.error


def test_run_tempo_mapping_normalizes_measures_so_pre_first_beat_events_are_not_dropped(
    tmp_path, source
):
    store = JobStore()
    job = store.create(url=source.url)
    # e1 (0.5s) and e2 (3.0s) both precede or straddle the first detected
    # beat (2.5s). Quantized against FakeOffsetBeatDetector's beats without
    # normalization, e1 would land at measure 0 and e2 at measure 1 - the
    # frontend's 1-based buildMeasures would silently drop e1. A uniform
    # +1 shift should make every measure >= 1 while preserving the exact
    # 1-measure/1-beat spacing between them (absolute beat index -4 -> 1).
    events = [
        DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=3.0, instrument=DrumInstrument.SNARE),
    ]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeOffsetBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.TEMPO_MAPPED
    e1, e2 = updated.events
    assert e1.measure >= 1
    assert e2.measure >= 1
    assert e1.measure == 1
    assert e1.beat == 1
    assert e1.subdivision == 0
    assert e2.measure == 2
    assert e2.beat == 2
    assert e2.subdivision == 0


def test_run_tempo_mapping_does_not_shift_measures_when_all_are_already_at_least_one(
    tmp_path, source
):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.TEMPO_MAPPED
    assert updated.events[0].measure == 1
    assert updated.events[0].beat == 2


def test_run_transcription_stores_raw_events_alongside_events(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)

    run_transcription(job.id, tmp_path / "drums.wav", store, FakeSuccessfulTranscriber())

    updated = store.get(job.id)
    assert updated.raw_events == [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]


def test_run_tempo_mapping_does_not_modify_raw_events(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    raw_events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]
    store.update(job.id, raw_events=raw_events)

    run_tempo_mapping(
        job.id,
        tmp_path / "drums.wav",
        raw_events,
        store,
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
    )

    updated = store.get(job.id)
    assert updated.raw_events == raw_events
    assert updated.raw_events[0].beat is None
    assert updated.events[0].beat is not None


def test_run_pipeline_preserves_raw_events_separately_from_quantized_events(tmp_path, source):
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
        FakeSuccessfulBeatDetector(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert updated.raw_events == [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]
    assert updated.raw_events[0].beat is None
    assert updated.events[0].beat is not None


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
        FakeSuccessfulBeatDetector(),
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
        FakeSuccessfulBeatDetector(),
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
        FakeSuccessfulBeatDetector(),
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
        FakeSuccessfulBeatDetector(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "transcription blew up"
    assert estimator_called is False


def test_run_pipeline_resumes_from_stem_separation_when_audio_already_downloaded(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    audio_path = tmp_path / job.id / "source.wav"
    store.update(job.id, status=JobStatus.FAILED, audio_path=str(audio_path))
    extractor_called = False

    class SpyExtractor:
        def extract(self, source, destination_dir):
            nonlocal extractor_called
            extractor_called = True
            return destination_dir / "source.wav"

    run_pipeline(
        job.id,
        source,
        store,
        SpyExtractor(),
        FakeSuccessfulSeparator(),
        FakeSuccessfulTranscriber(),
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert extractor_called is False
    assert updated.status == JobStatus.TEMPO_MAPPED


def test_run_pipeline_resumes_from_transcription_when_stems_already_separated(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    audio_path = tmp_path / job.id / "source.wav"
    drums_path = tmp_path / "drums.wav"
    store.update(
        job.id,
        status=JobStatus.FAILED,
        audio_path=str(audio_path),
        drums_path=str(drums_path),
        accompaniment_path=str(tmp_path / "no_drums.wav"),
    )
    separator_called = False

    class SpySeparator:
        def separate(self, audio_path, destination_dir):
            nonlocal separator_called
            separator_called = True
            return SeparatedStems(
                drums_path=destination_dir / "drums.wav",
                accompaniment_path=destination_dir / "no_drums.wav",
            )

    run_pipeline(
        job.id,
        source,
        store,
        FakeSuccessfulExtractor(),
        SpySeparator(),
        FakeSuccessfulTranscriber(),
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert separator_called is False
    assert updated.status == JobStatus.TEMPO_MAPPED


def test_run_pipeline_resumes_from_tempo_mapping_when_events_already_transcribed(tmp_path, source):
    store = JobStore()
    job = store.create(url=source.url)
    events = [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]
    store.update(
        job.id,
        status=JobStatus.FAILED,
        audio_path=str(tmp_path / job.id / "source.wav"),
        drums_path=str(tmp_path / "drums.wav"),
        accompaniment_path=str(tmp_path / "no_drums.wav"),
        events=events,
    )
    transcriber_called = False

    class SpyTranscriber:
        def transcribe(self, audio_path):
            nonlocal transcriber_called
            transcriber_called = True
            return events

    run_pipeline(
        job.id,
        source,
        store,
        FakeSuccessfulExtractor(),
        FakeSuccessfulSeparator(),
        SpyTranscriber(),
        FakeSuccessfulTempoEstimator(),
        FakeSuccessfulBeatDetector(),
        tmp_path,
    )

    updated = store.get(job.id)
    assert transcriber_called is False
    assert updated.status == JobStatus.TEMPO_MAPPED


def test_concurrency_limiter_runs_calls_immediately_up_to_the_configured_limit():
    limiter = PipelineConcurrencyLimiter(max_concurrent=2)
    running: list[str] = []
    lock = threading.Lock()
    release = threading.Event()

    def task(name: str) -> None:
        with lock:
            running.append(name)
        release.wait(timeout=2)

    threads = [threading.Thread(target=limiter.run, args=(task, f"job-{i}")) for i in range(2)]
    for t in threads:
        t.start()
    time.sleep(0.1)

    assert sorted(running) == ["job-0", "job-1"]

    release.set()
    for t in threads:
        t.join(timeout=2)


def test_concurrency_limiter_blocks_additional_calls_until_a_slot_frees_up():
    limiter = PipelineConcurrencyLimiter(max_concurrent=1)
    running: list[str] = []
    lock = threading.Lock()
    first_started = threading.Event()
    release_first = threading.Event()

    def first_task() -> None:
        with lock:
            running.append("first")
        first_started.set()
        release_first.wait(timeout=2)

    def second_task() -> None:
        with lock:
            running.append("second")

    first_thread = threading.Thread(target=limiter.run, args=(first_task,))
    first_thread.start()
    first_started.wait(timeout=2)

    second_thread = threading.Thread(target=limiter.run, args=(second_task,))
    second_thread.start()
    time.sleep(0.1)

    assert running == ["first"]

    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert running == ["first", "second"]
