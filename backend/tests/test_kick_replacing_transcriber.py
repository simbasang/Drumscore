from pathlib import Path

import pytest

from app.kick_replacing_transcriber import KickReplacingTranscriber
from app.transcription import ComposedTranscriber, DrumEvent, DrumInstrument, TranscriptionError

AUDIO = Path("drums.wav")


class _FakeTranscriber:
    def __init__(self, events: list[DrumEvent] | None = None, error: Exception | None = None) -> None:
        self._events = events or []
        self._error = error

    def transcribe(self, audio_path: Path) -> list[DrumEvent]:
        if self._error is not None:
            raise self._error
        return self._events


class _FakeDetector:
    def __init__(self, times: list[float]) -> None:
        self._times = times
        self.paths: list[Path] = []

    def detect(self, audio_path: Path) -> list[float]:
        self.paths.append(audio_path)
        return self._times


def _base(time: float, instrument: DrumInstrument) -> DrumEvent:
    return DrumEvent(id=f"base-{time}", time=time, instrument=instrument, provenance="drumscript")


def test_replaces_base_kicks_with_detector_kicks():
    base = [_base(1.0, DrumInstrument.KICK), _base(2.0, DrumInstrument.SNARE)]
    transcriber = KickReplacingTranscriber(_FakeTranscriber(base), _FakeDetector([1.01, 3.0]))

    result = transcriber.transcribe(AUDIO)

    assert [(event.time, event.instrument, event.provenance) for event in result] == [
        (1.01, DrumInstrument.KICK, "kick_detector"),
        (2.0, DrumInstrument.SNARE, "drumscript"),
        (3.0, DrumInstrument.KICK, "kick_detector"),
    ]


def test_keeps_base_non_kick_events_unchanged():
    base = [_base(1.0, DrumInstrument.SNARE), _base(1.0, DrumInstrument.HIHAT_CLOSED)]
    transcriber = KickReplacingTranscriber(_FakeTranscriber(base), _FakeDetector([]))

    result = transcriber.transcribe(AUDIO)

    assert result == base


def test_detector_kicks_have_ids_and_no_confidence():
    detector = _FakeDetector([2.0, 3.0])
    transcriber = KickReplacingTranscriber(_FakeTranscriber([]), detector)

    result = transcriber.transcribe(AUDIO)

    assert all(event.confidence is None for event in result)
    assert len({event.id for event in result}) == 2
    assert detector.paths == [AUDIO]


def test_result_is_sorted_by_time():
    base = [_base(1.0, DrumInstrument.SNARE), _base(3.0, DrumInstrument.SNARE)]
    transcriber = KickReplacingTranscriber(_FakeTranscriber(base), _FakeDetector([2.0, 0.5]))

    result = transcriber.transcribe(AUDIO)

    assert [event.time for event in result] == [0.5, 1.0, 2.0, 3.0]


def test_transcribe_with_engine_output_returns_the_unmodified_base_events():
    base = [_base(1.0, DrumInstrument.KICK), _base(2.0, DrumInstrument.SNARE)]
    transcriber = KickReplacingTranscriber(_FakeTranscriber(base), _FakeDetector([3.0]))

    events, engine_events = transcriber.transcribe_with_engine_output(AUDIO)

    assert engine_events == base
    assert [event.time for event in events] == [2.0, 3.0]


def test_is_a_composed_transcriber():
    transcriber = KickReplacingTranscriber(_FakeTranscriber([]), _FakeDetector([]))

    assert isinstance(transcriber, ComposedTranscriber)


def test_plain_transcriber_is_not_a_composed_transcriber():
    assert not isinstance(_FakeTranscriber([]), ComposedTranscriber)


def test_base_transcription_error_propagates():
    transcriber = KickReplacingTranscriber(_FakeTranscriber(error=TranscriptionError("boom")), _FakeDetector([1.0]))

    with pytest.raises(TranscriptionError, match="boom"):
        transcriber.transcribe(AUDIO)
