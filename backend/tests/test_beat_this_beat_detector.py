import numpy as np
import pytest
import soundfile as sf

from app.beat_detection import BeatDetectionError
from app.beat_this_beat_detector import BeatThisBeatDetector, beat_points_from_tracker, tempo_from_beats
from app.timing import BeatPoint


def _beats_at(times: list[float]) -> list[BeatPoint]:
    return beat_points_from_tracker(times, [])


def test_numbers_beats_in_fours_from_the_first_beat_when_it_is_a_downbeat():
    beat_times = [0.5 * i for i in range(8)]

    beats = beat_points_from_tracker(beat_times, [0.0, 2.0])

    assert [(b.measure, b.beat) for b in beats] == [
        (1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (2, 2), (2, 3), (2, 4),
    ]


def test_puts_pickup_beats_before_the_first_downbeat_in_measure_one():
    beat_times = [0.5 * i for i in range(8)]

    beats = beat_points_from_tracker(beat_times, [1.0, 3.0])

    assert [(b.measure, b.beat, b.is_downbeat) for b in beats[:3]] == [
        (1, 3, False), (1, 4, False), (2, 1, True),
    ]


def test_follows_the_majority_downbeat_phase_when_one_downbeat_is_off():
    beat_times = [0.5 * i for i in range(16)]

    beats = beat_points_from_tracker(beat_times, [0.0, 2.0, 4.5, 6.0])

    assert [b.source_time for b in beats if b.is_downbeat] == [0.0, 2.0, 4.0, 6.0]


def test_matches_downbeats_to_the_nearest_beat():
    beat_times = [0.5 * i for i in range(8)]

    beats = beat_points_from_tracker(beat_times, [0.52, 2.49])

    assert beats[1].is_downbeat
    assert beats[5].is_downbeat


def test_starts_at_beat_one_when_no_downbeats_are_detected():
    beats = beat_points_from_tracker([0.3, 0.8, 1.3], [])

    assert [(b.measure, b.beat) for b in beats] == [(1, 1), (1, 2), (1, 3)]


def test_keeps_tracker_beat_times_unchanged_as_source_times():
    beat_times = [0.31, 0.83, 1.37, 1.88, 2.44]

    beats = beat_points_from_tracker(beat_times, [0.31])

    assert [b.source_time for b in beats] == beat_times


def test_leaves_confidence_empty():
    beats = beat_points_from_tracker([0.0, 0.5], [0.0])

    assert all(b.confidence is None for b in beats)


def test_returns_no_beats_for_an_empty_tracker_result():
    beats = beat_points_from_tracker([], [])

    assert beats == []


def test_tempo_from_beats_is_not_quantized_to_single_frame_intervals():
    period = 60.0 / 113.0
    beat_times = [round(i * period / 0.02) * 0.02 for i in range(200)]

    bpm = tempo_from_beats(_beats_at(beat_times))

    assert bpm == pytest.approx(113.0, abs=0.5)


def test_tempo_from_beats_ignores_a_single_missed_beat():
    beat_times = [0.5 * i for i in range(40) if i != 17]

    bpm = tempo_from_beats(_beats_at(beat_times))

    assert bpm == pytest.approx(120.0)


def test_tempo_from_beats_uses_single_intervals_for_short_sequences():
    bpm = tempo_from_beats(_beats_at([1.0, 1.5, 2.0]))

    assert bpm == pytest.approx(120.0)


@pytest.mark.parametrize("beat_times", [[], [1.0]])
def test_tempo_from_beats_rejects_fewer_than_two_beats(beat_times):
    beats = _beats_at(beat_times)

    with pytest.raises(ValueError, match="at least 2 beats"):
        tempo_from_beats(beats)


def _write_wav(path, samples, sr=8000):
    sf.write(str(path), np.asarray(samples, dtype=np.float32), sr, subtype="FLOAT")
    return path


def _stems(tmp_path):
    drums = _write_wav(tmp_path / "drums.wav", [0.1, 0.2])
    accompaniment = _write_wav(tmp_path / "accompaniment.wav", [0.3, -0.1])
    return drums, accompaniment


def test_detect_tracks_the_mix_of_both_stems(tmp_path):
    drums, accompaniment = _stems(tmp_path)
    heard = []

    def tracker(path):
        heard.append(sf.read(str(path))[0].tolist())
        return np.array([0.5, 1.0]), np.array([0.5])

    BeatThisBeatDetector(tracker=tracker).detect(drums, accompaniment)

    assert heard == [pytest.approx([0.4, 0.1])]


def test_detect_regularizes_the_tracked_beats(tmp_path):
    drums, accompaniment = _stems(tmp_path)
    tracked = [0.5 * i for i in range(20)]
    tracked.insert(8, 3.6)

    beats = BeatThisBeatDetector(tracker=lambda path: (np.array(tracked), np.array([0.0]))).detect(
        drums, accompaniment
    )

    assert [b.source_time for b in beats] == [0.5 * i for i in range(20)]


def test_detect_removes_the_temporary_mix_when_tracking_fails(tmp_path):
    drums, accompaniment = _stems(tmp_path)
    mixes = []

    def tracker(path):
        mixes.append(path)
        raise RuntimeError("decode failed")

    with pytest.raises(BeatDetectionError, match="decode failed"):
        BeatThisBeatDetector(tracker=tracker).detect(drums, accompaniment)

    assert not mixes[0].exists()


def test_detect_wraps_unreadable_stems_in_beat_detection_error(tmp_path):
    (tmp_path / "drums.wav").write_bytes(b"not audio")
    accompaniment = _write_wav(tmp_path / "accompaniment.wav", [0.1])

    with pytest.raises(BeatDetectionError):
        BeatThisBeatDetector(tracker=lambda path: (np.array([]), np.array([]))).detect(
            tmp_path / "drums.wav", accompaniment
        )


def _write_accented_click_track(path, bpm: float, duration_seconds: float = 12.0, sr: int = 22050) -> None:
    y = np.zeros(int(duration_seconds * sr))
    click = np.exp(-np.linspace(0, 30, int(0.05 * sr))) * np.sin(np.linspace(0, 2 * np.pi * 50, int(0.05 * sr)))
    for index, t in enumerate(np.arange(0.5, duration_seconds, 60.0 / bpm)):
        start = int(t * sr)
        end = min(start + len(click), len(y))
        gain = 1.0 if index % 4 == 0 else 0.5
        y[start:end] += gain * click[: end - start]
    sf.write(str(path), y, sr)


def test_detect_finds_a_click_track_tempo_with_the_real_model(tmp_path):
    drums = tmp_path / "clicks.wav"
    _write_accented_click_track(drums, bpm=100.0)
    silence = _write_wav(tmp_path / "silence.wav", np.zeros(22050), sr=22050)

    beats = BeatThisBeatDetector().detect(drums, silence)

    assert tempo_from_beats(beats) == pytest.approx(100.0, rel=0.04)
