from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.audio_extraction import ExtractedAudio
from app.stem_separation import SeparatedStems
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument

START = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

FOUR_BEATS = [
    BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True),
    BeatPoint(source_time=0.5, measure=1, beat=2, is_downbeat=False),
    BeatPoint(source_time=1.0, measure=1, beat=3, is_downbeat=False),
    BeatPoint(source_time=1.5, measure=1, beat=4, is_downbeat=False),
]

# First beat NOT at t=0 - distinguishes beat-anchored quantization from a t=0 grid.
OFFSET_BEATS = [
    BeatPoint(source_time=2.5, measure=1, beat=1, is_downbeat=True),
    BeatPoint(source_time=3.0, measure=1, beat=2, is_downbeat=False),
    BeatPoint(source_time=3.5, measure=1, beat=3, is_downbeat=False),
]

SAMPLE_RAW_EVENTS = [
    DrumEvent(id="e1", time=0.5 + 1e-9, instrument=DrumInstrument.KICK, provenance="drumscript"),
    DrumEvent(id="e2", time=0.5 + 1e-9, instrument=DrumInstrument.HIHAT_CLOSED, provenance="drumscript"),
]


class FakeClock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class FakeExtractor:
    def __init__(self, title: str | None = "Fake Song", error: BaseException | None = None, on_call=None) -> None:
        self.title = title
        self.error = error
        self.on_call = on_call
        self.calls = 0

    def extract(self, source, destination_dir: Path) -> ExtractedAudio:
        self.calls += 1
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        destination_dir.mkdir(parents=True, exist_ok=True)
        path = destination_dir / "source.wav"
        path.write_bytes(b"fake source audio")
        return ExtractedAudio(audio_path=path, title=self.title)


class FakeSeparator:
    def __init__(self, error: BaseException | None = None, on_call=None) -> None:
        self.error = error
        self.on_call = on_call
        self.calls = 0

    def separate(self, audio_path: Path, destination_dir: Path) -> SeparatedStems:
        self.calls += 1
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        assert audio_path.read_bytes() == b"fake source audio"
        output = destination_dir / "htdemucs" / "source"
        output.mkdir(parents=True, exist_ok=True)
        (output / "drums.wav").write_bytes(b"fake drums")
        (output / "no_drums.wav").write_bytes(b"fake accompaniment")
        return SeparatedStems(drums_path=output / "drums.wav", accompaniment_path=output / "no_drums.wav")


class FakeTranscriber:
    def __init__(self, events=None, error: BaseException | None = None) -> None:
        self.events = list(SAMPLE_RAW_EVENTS if events is None else events)
        self.error = error
        self.calls = 0

    def transcribe(self, audio_path: Path):
        self.calls += 1
        if self.error:
            raise self.error
        assert audio_path.read_bytes() == b"fake drums"
        return list(self.events)


class FakeTempoEstimator:
    def __init__(self, bpm: float = 120.0, error: BaseException | None = None) -> None:
        self.bpm = bpm
        self.error = error

    def estimate(self, audio_path: Path) -> float:
        if self.error:
            raise self.error
        return self.bpm


class FakeBeatDetector:
    def __init__(self, beats=None, error: BaseException | None = None) -> None:
        self.beats = list(FOUR_BEATS if beats is None else beats)
        self.error = error

    def detect(self, audio_path: Path):
        if self.error:
            raise self.error
        return list(self.beats)


def logged_events(caplog, event: str) -> list[dict]:
    """Structured events (app.observability.logging.log_event) named
    `event`, as {**bound context, **event fields}, in log order."""
    return [
        {**getattr(record, "context", {}), **getattr(record, "fields", {})}
        for record in caplog.records
        if record.getMessage() == event and hasattr(record, "fields")
    ]


def make_engines(**overrides):
    from app.pipeline.runner import PipelineEngines
    from app.youtube_source import YouTubeSourceValidator

    engines = {
        "source_validator": YouTubeSourceValidator(),
        "extractor": FakeExtractor(),
        "separator": FakeSeparator(),
        "transcriber": FakeTranscriber(),
        "tempo_estimator": FakeTempoEstimator(),
        "beat_detector": FakeBeatDetector(),
    }
    engines.update(overrides)
    return PipelineEngines(**engines)
