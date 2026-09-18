from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from app.librosa_tempo_estimator import LibrosaTempoEstimator
from app.tempo_estimation import TempoEstimationError


def _write_click_track(path, bpm: float, duration_seconds: float = 8.0, sr: int = 22050) -> None:
    seconds_per_beat = 60.0 / bpm
    y = np.zeros(int(duration_seconds * sr))
    click = np.exp(-np.linspace(0, 30, int(0.05 * sr)))

    t = 0.0
    while t < duration_seconds:
        start = int(t * sr)
        end = min(start + len(click), len(y))
        y[start:end] += click[: end - start]
        t += seconds_per_beat

    sf.write(str(path), y, sr)


def test_estimate_returns_bpm_close_to_known_click_track_tempo(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)

    bpm = LibrosaTempoEstimator().estimate(audio_path)

    assert 110.0 <= bpm <= 130.0


def test_estimate_corrects_an_octave_error_when_beat_tracker_halves_the_true_tempo(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)
    true_period = 60.0 / 120.0
    onset_times = np.arange(0, 8.0, true_period)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(60.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=onset_times),
    ):
        bpm = LibrosaTempoEstimator().estimate(audio_path)

    assert bpm == pytest.approx(120.0, abs=1.0)


def test_estimate_corrects_an_octave_error_when_beat_tracker_doubles_the_true_tempo(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=80.0)
    true_period = 60.0 / 80.0
    onset_times = np.arange(0, 8.0, true_period)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(160.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=onset_times),
    ):
        bpm = LibrosaTempoEstimator().estimate(audio_path)

    assert bpm == pytest.approx(80.0, abs=1.0)


def test_estimate_keeps_tempo_unchanged_when_it_already_fits_the_onset_grid(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)
    true_period = 60.0 / 120.0
    onset_times = np.arange(0, 8.0, true_period)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(120.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=onset_times),
    ):
        bpm = LibrosaTempoEstimator().estimate(audio_path)

    assert bpm == pytest.approx(120.0, abs=1.0)


def test_estimate_leaves_tempo_unchanged_when_no_onsets_are_detected(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(120.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=np.array([])),
    ):
        bpm = LibrosaTempoEstimator().estimate(audio_path)

    assert bpm == pytest.approx(120.0)


def test_estimate_raises_on_invalid_audio_file(tmp_path):
    bad_path = tmp_path / "not_audio.wav"
    bad_path.write_bytes(b"not a real wav file")

    with pytest.raises(TempoEstimationError):
        LibrosaTempoEstimator().estimate(bad_path)
