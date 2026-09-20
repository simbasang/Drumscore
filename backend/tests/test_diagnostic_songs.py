import numpy as np
import pytest

from app.transcription import DrumInstrument
from tests.fixtures.diagnostic_songs import ExpectedHit, render_events


def test_render_events_is_silent_before_a_hits_onset():
    hits = [ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)]

    audio = render_events(hits, duration_seconds=2.0, sample_rate=22050)

    onset_sample = int(1.0 * 22050)
    assert np.all(audio[: onset_sample - 1] == 0.0)


def test_render_events_produces_a_nonzero_onset_at_the_hit_time():
    hits = [ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)]

    audio = render_events(hits, duration_seconds=2.0, sample_rate=22050)

    onset_sample = int(1.0 * 22050)
    window = audio[onset_sample : onset_sample + 200]
    assert np.max(np.abs(window)) > 0.0


def test_render_events_matches_declared_duration_and_sample_rate():
    audio = render_events([], duration_seconds=1.5, sample_rate=22050)

    assert len(audio) == int(round(1.5 * 22050))


def test_render_events_is_deterministic_across_calls():
    hits = [
        ExpectedHit(time=0.1, instrument=DrumInstrument.SNARE),
        ExpectedHit(time=0.2, instrument=DrumInstrument.HIHAT_CLOSED),
    ]

    first = render_events(hits, duration_seconds=1.0, sample_rate=22050)
    second = render_events(hits, duration_seconds=1.0, sample_rate=22050)

    np.testing.assert_array_equal(first, second)


def test_render_events_stays_within_the_minus_one_to_one_range():
    hits = [ExpectedHit(time=t, instrument=DrumInstrument.CRASH) for t in (0.0, 0.05, 0.1, 0.15)]

    audio = render_events(hits, duration_seconds=1.0, sample_rate=22050)

    assert np.max(np.abs(audio)) <= 1.0
