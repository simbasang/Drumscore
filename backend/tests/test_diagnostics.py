import pytest

from app.beat_mapping import quantize_events_with_beats
from app.diagnostics import build_event_diagnostics
from app.timing import BeatPoint
from app.transcription import DrumEvent, DrumInstrument


def _beat(time: float, measure: int, beat: int) -> BeatPoint:
    return BeatPoint(source_time=time, measure=measure, beat=beat, is_downbeat=beat == 1)


# Evenly spaced beats starting at t=0 - equivalent to a constant 120bpm
# grid, so expected quantized_time/error values below are easy to reason
# about by hand.
CONSTANT_TEMPO_BEATS = [
    _beat(0.0, 1, 1),
    _beat(0.5, 1, 2),
    _beat(1.0, 1, 3),
    _beat(1.5, 1, 4),
    _beat(2.0, 2, 1),
]

OFFSET_BEATS = [
    BeatPoint(source_time=2.5, measure=1, beat=1, is_downbeat=True),
    BeatPoint(source_time=3.0, measure=1, beat=2, is_downbeat=False),
    BeatPoint(source_time=3.5, measure=1, beat=3, is_downbeat=False),
]


def test_build_event_diagnostics_traces_each_quantized_event_back_to_its_raw_source():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].event_id == "e1"
    assert diagnostics[0].source_time == 0.13
    assert diagnostics[0].instrument == DrumInstrument.SNARE


def test_build_event_diagnostics_reports_the_quantization_error_in_seconds():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    # 0.13s quantizes to subdivision 1 (0.125s) on the 120bpm-equivalent grid.
    assert diagnostics[0].quantized_time == pytest.approx(0.125)
    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.125 - 0.13)


def test_build_event_diagnostics_reports_zero_error_for_perfectly_grid_aligned_hits():
    raw_events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.0, abs=1e-9)


def test_build_event_diagnostics_preserves_order_and_count():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=0.5, instrument=DrumInstrument.SNARE),
    ]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert [d.event_id for d in diagnostics] == ["e1", "e2"]


def test_build_event_diagnostics_passes_through_velocity_and_confidence():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK, velocity=0.8, confidence=0.9)
    ]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].velocity == 0.8
    assert diagnostics[0].confidence == 0.9


def test_build_event_diagnostics_passes_through_provenance():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK, provenance="drumscript")
    ]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].provenance == "drumscript"


def test_build_event_diagnostics_leaves_quantized_fields_none_when_no_matching_quantized_event():
    raw_events = [DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK)]

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events=[], tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert diagnostics[0].measure is None
    assert diagnostics[0].quantized_time is None
    assert diagnostics[0].quantization_error_seconds is None


def test_build_event_diagnostics_does_not_mutate_its_inputs():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, CONSTANT_TEMPO_BEATS)
    raw_events_before = list(raw_events)
    quantized_events_before = list(quantized_events)

    build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=CONSTANT_TEMPO_BEATS
    )

    assert raw_events == raw_events_before
    assert quantized_events == quantized_events_before


def test_build_event_diagnostics_reconstructs_quantized_time_using_beat_anchors():
    raw_events = [DrumEvent(id="e1", time=2.5, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events_with_beats(raw_events, OFFSET_BEATS)

    diagnostics = build_event_diagnostics(
        raw_events, quantized_events, tempo_bpm=120.0, beats=OFFSET_BEATS
    )

    # An event exactly at the first real beat (2.5s) must reconstruct back
    # to exactly 2.5s via the beat-anchored inverse - a t=0-anchored
    # reconstruction would instead return 0.0s, since it would assume
    # measure 1 beat 1 is at t=0.
    assert diagnostics[0].quantized_time == pytest.approx(2.5)
    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.0, abs=1e-9)
