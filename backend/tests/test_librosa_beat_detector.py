from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from app.beat_detection import BeatDetectionError
from app.librosa_beat_detector import LibrosaBeatDetector
from tests.fixtures.diagnostic_songs import get_diagnostic_song


def _write_click_track_with_lead_in(
    path, bpm: float, lead_in_seconds: float, duration_seconds: float = 8.0, sr: int = 22050
) -> None:
    seconds_per_beat = 60.0 / bpm
    total_samples = int(duration_seconds * sr)
    y = np.zeros(total_samples)
    click = np.exp(-np.linspace(0, 30, int(0.05 * sr)))

    t = lead_in_seconds
    while t < duration_seconds:
        start = int(t * sr)
        end = min(start + len(click), total_samples)
        if start < total_samples:
            y[start:end] += click[: end - start]
        t += seconds_per_beat

    sf.write(str(path), y, sr)


def test_detect_anchors_the_first_beat_to_real_lead_in_silence_not_zero(tmp_path):
    # bpm=120, 1.0s of lead-in silence before the first click. This lead-in
    # value is empirically verified (see the plan doc) to give a stable,
    # non-octave-confused tempo estimate for this synthesis.
    audio_path = tmp_path / "clicks.wav"
    _write_click_track_with_lead_in(audio_path, bpm=120.0, lead_in_seconds=1.0)

    beats = LibrosaBeatDetector().detect(audio_path)

    assert len(beats) > 0
    assert beats[0].source_time == pytest.approx(1.0, abs=0.1)
    assert beats[0].source_time > 0.5
    assert beats[0].is_downbeat is True
    assert beats[0].measure == 1
    assert beats[0].beat == 1


def test_detect_marks_every_fourth_beat_as_a_downbeat_with_increasing_measures(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track_with_lead_in(audio_path, bpm=120.0, lead_in_seconds=1.0)

    beats = LibrosaBeatDetector().detect(audio_path)

    assert [b.is_downbeat for b in beats[:8]] == [
        True,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    assert [b.beat for b in beats[:8]] == [1, 2, 3, 4, 1, 2, 3, 4]
    assert [b.measure for b in beats[:8]] == [1, 1, 1, 1, 2, 2, 2, 2]


def test_detect_produces_source_times_in_strictly_increasing_order(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track_with_lead_in(audio_path, bpm=120.0, lead_in_seconds=1.0)

    beats = LibrosaBeatDetector().detect(audio_path)
    times = [b.source_time for b in beats]

    assert times == sorted(times)
    assert len(set(times)) == len(times)


def test_detect_is_deterministic_across_repeated_calls(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track_with_lead_in(audio_path, bpm=120.0, lead_in_seconds=1.0)

    first_run = LibrosaBeatDetector().detect(audio_path)
    second_run = LibrosaBeatDetector().detect(audio_path)

    assert first_run == second_run


def test_detect_maps_the_intro_count_in_fixture_correctly(tmp_path):
    song = get_diagnostic_song("intro_count_in")
    audio_path = tmp_path / "intro_count_in.wav"
    song.write_wav(audio_path)

    beats = LibrosaBeatDetector().detect(audio_path)

    # The detector doesn't know "count-in" is semantically different from a
    # real downbeat - it just finds the true beat grid. Proving it no longer
    # assumes t=0:
    assert beats[0].source_time == pytest.approx(0.5, abs=0.1)
    assert beats[0].source_time > 0.3
    assert beats[0].is_downbeat is True

    # And proving the phase-aligned 4-beat grid recovers the fixture's own
    # declared true musical downbeat (2.5s), purely from counting forward:
    assert any(
        b.is_downbeat and b.source_time == pytest.approx(song.downbeat_offset_seconds, abs=0.1)
        for b in beats
    )


def test_detect_raises_when_no_onsets_are_detected(tmp_path):
    audio_path = tmp_path / "silence.wav"
    sf.write(str(audio_path), np.zeros(22050 * 2), 22050)

    with (
        patch("app.librosa_beat_detector.LibrosaTempoEstimator.estimate", return_value=120.0),
        patch("app.librosa_beat_detector.librosa.onset.onset_detect", return_value=np.array([])),
    ):
        with pytest.raises(BeatDetectionError, match="No onsets"):
            LibrosaBeatDetector().detect(audio_path)


def test_detect_wraps_tempo_estimation_failures(tmp_path):
    audio_path = tmp_path / "bad.wav"
    audio_path.write_bytes(b"not a real wav file")

    with pytest.raises(BeatDetectionError):
        LibrosaBeatDetector().detect(audio_path)
