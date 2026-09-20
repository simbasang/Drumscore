import pytest

from app.beat_mapping import quantize_events
from app.diagnostics import build_event_diagnostics
from app.transcription import DrumEvent, DrumInstrument


def test_build_event_diagnostics_traces_each_quantized_event_back_to_its_raw_source():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert diagnostics[0].event_id == "e1"
    assert diagnostics[0].source_time == 0.13
    assert diagnostics[0].instrument == DrumInstrument.SNARE


def test_build_event_diagnostics_reports_the_quantization_error_in_seconds():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    # 0.13s quantizes to subdivision 1 (0.125s) at 120 BPM.
    assert diagnostics[0].quantized_time == pytest.approx(0.125)
    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.125 - 0.13)


def test_build_event_diagnostics_reports_zero_error_for_perfectly_grid_aligned_hits():
    raw_events = [DrumEvent(id="e1", time=0.5, instrument=DrumInstrument.KICK)]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert diagnostics[0].quantization_error_seconds == pytest.approx(0.0, abs=1e-9)


def test_build_event_diagnostics_preserves_order_and_count():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK),
        DrumEvent(id="e2", time=0.5, instrument=DrumInstrument.SNARE),
    ]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert [d.event_id for d in diagnostics] == ["e1", "e2"]


def test_build_event_diagnostics_passes_through_velocity_and_confidence():
    raw_events = [
        DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK, velocity=0.8, confidence=0.9)
    ]
    quantized_events = quantize_events(raw_events, bpm=120.0)

    diagnostics = build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert diagnostics[0].velocity == 0.8
    assert diagnostics[0].confidence == 0.9


def test_build_event_diagnostics_leaves_quantized_fields_none_when_no_matching_quantized_event():
    raw_events = [DrumEvent(id="e1", time=0.0, instrument=DrumInstrument.KICK)]

    diagnostics = build_event_diagnostics(raw_events, quantized_events=[], tempo_bpm=120.0)

    assert diagnostics[0].measure is None
    assert diagnostics[0].quantized_time is None
    assert diagnostics[0].quantization_error_seconds is None


def test_build_event_diagnostics_does_not_mutate_its_inputs():
    raw_events = [DrumEvent(id="e1", time=0.13, instrument=DrumInstrument.SNARE)]
    quantized_events = quantize_events(raw_events, bpm=120.0)
    raw_events_before = list(raw_events)
    quantized_events_before = list(quantized_events)

    build_event_diagnostics(raw_events, quantized_events, tempo_bpm=120.0)

    assert raw_events == raw_events_before
    assert quantized_events == quantized_events_before
