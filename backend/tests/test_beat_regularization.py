import numpy as np
import pytest

from app.beat_regularization import regularize_beats, typical_beat_period


def test_keeps_a_steady_beat_sequence_unchanged():
    beats = [0.5 * i for i in range(20)]

    result = regularize_beats(beats)

    assert result == beats


def test_drops_a_spurious_beat_between_two_real_beats():
    beats = [0.5 * i for i in range(20)]
    beats.insert(8, 3.6)

    result = regularize_beats(beats)

    assert result == [0.5 * i for i in range(20)]


def test_prefers_the_detection_nearest_the_expected_beat():
    beats = [0.5 * i for i in range(20)]
    beats.insert(8, 3.85)

    result = regularize_beats(beats)

    assert 3.85 not in result
    assert 4.0 in result


def test_keeps_every_other_beat_in_a_double_time_section():
    steady = [0.5 * i for i in range(20)]
    double_time = [10.0 + 0.25 * i for i in range(20)]
    resumed = [15.0 + 0.5 * i for i in range(40)]

    result = regularize_beats(steady + double_time + resumed)

    assert result == [0.5 * i for i in range(70)]


def test_keeps_the_real_beats_of_a_double_time_intro_that_starts_off_the_beat():
    intro = [0.25 * i for i in range(1, 18)]
    steady = [4.5 + 0.5 * i for i in range(40)]

    result = regularize_beats(intro + steady)

    assert result == [0.5 * i for i in range(1, 49)]


def test_drops_a_spurious_first_detection_just_before_the_first_beat():
    beats = [1.8] + [2.0 + 0.5 * i for i in range(20)]

    result = regularize_beats(beats)

    assert result == [2.0 + 0.5 * i for i in range(20)]


def test_fills_a_skipped_beat_with_an_interpolated_one():
    beats = [0.5 * i for i in range(20) if i != 9]

    result = regularize_beats(beats)

    assert result == pytest.approx([0.5 * i for i in range(20)])


def test_fills_a_long_gap_evenly_and_resumes_on_the_next_detection():
    beats = [0.5 * i for i in range(10)] + [10.1 + 0.5 * i for i in range(10)]

    result = regularize_beats(beats)

    assert len(result) == 30
    assert result[20] == 10.1
    assert np.diff(result[9:21]) == pytest.approx([(10.1 - 4.5) / 11] * 11)


def test_follows_a_gradual_tempo_drift():
    periods = np.linspace(0.5, 0.56, 120)
    beats = list(np.concatenate([[0.0], np.cumsum(periods)]))

    result = regularize_beats(beats)

    assert result == beats


@pytest.mark.parametrize("beats", [[], [1.0], [1.0, 1.5]])
def test_returns_very_short_sequences_unchanged(beats):
    result = regularize_beats(beats)

    assert result == beats


def test_typical_beat_period_is_the_median_over_four_beat_spans():
    beats = [0.5 * i for i in range(40) if i != 17]

    period = typical_beat_period(beats)

    assert period == pytest.approx(0.5)
