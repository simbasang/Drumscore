import pytest

from app.timing import BeatPoint, TempoMap, TempoPoint


def test_tempo_point_stores_source_time_and_bpm():
    point = TempoPoint(source_time=1.5, bpm=120.0)

    assert point.source_time == 1.5
    assert point.bpm == 120.0


def test_tempo_point_rejects_a_negative_source_time():
    with pytest.raises(ValueError, match="source_time"):
        TempoPoint(source_time=-0.1, bpm=120.0)


def test_tempo_point_rejects_a_non_positive_bpm():
    with pytest.raises(ValueError, match="bpm"):
        TempoPoint(source_time=0.0, bpm=0.0)


def test_beat_point_stores_source_time_measure_beat_and_downbeat_flag():
    point = BeatPoint(source_time=2.0, measure=3, beat=1, is_downbeat=True)

    assert point.source_time == 2.0
    assert point.measure == 3
    assert point.beat == 1
    assert point.is_downbeat is True
    assert point.confidence is None


def test_beat_point_accepts_an_optional_confidence():
    point = BeatPoint(source_time=2.0, measure=1, beat=2, is_downbeat=False, confidence=0.87)

    assert point.confidence == 0.87


def test_beat_point_rejects_a_negative_source_time():
    with pytest.raises(ValueError, match="source_time"):
        BeatPoint(source_time=-1.0, measure=1, beat=1, is_downbeat=True)


def test_beat_point_rejects_a_measure_below_one():
    with pytest.raises(ValueError, match="measure"):
        BeatPoint(source_time=0.0, measure=0, beat=1, is_downbeat=True)


def test_beat_point_rejects_a_beat_below_one():
    with pytest.raises(ValueError, match="beat"):
        BeatPoint(source_time=0.0, measure=1, beat=0, is_downbeat=True)


def test_beat_point_rejects_a_confidence_outside_zero_to_one():
    with pytest.raises(ValueError, match="confidence"):
        BeatPoint(source_time=0.0, measure=1, beat=1, is_downbeat=True, confidence=1.5)


def test_tempo_map_rejects_an_empty_point_list():
    with pytest.raises(ValueError, match="at least one"):
        TempoMap(points=())


def test_tempo_map_rejects_points_not_sorted_by_source_time():
    with pytest.raises(ValueError, match="sorted"):
        TempoMap(
            points=(
                TempoPoint(source_time=1.0, bpm=120.0),
                TempoPoint(source_time=0.5, bpm=100.0),
            )
        )


def test_tempo_map_bpm_at_returns_the_tempo_in_effect_at_a_given_time():
    tempo_map = TempoMap(
        points=(
            TempoPoint(source_time=0.0, bpm=100.0),
            TempoPoint(source_time=10.0, bpm=140.0),
        )
    )

    assert tempo_map.bpm_at(0.0) == 100.0
    assert tempo_map.bpm_at(5.0) == 100.0
    assert tempo_map.bpm_at(10.0) == 140.0
    assert tempo_map.bpm_at(20.0) == 140.0


def test_tempo_map_bpm_at_uses_the_first_point_before_any_point_exists():
    tempo_map = TempoMap(points=(TempoPoint(source_time=2.0, bpm=90.0),))

    assert tempo_map.bpm_at(0.0) == 90.0


def test_tempo_map_constant_builds_a_single_point_map_anchored_at_zero():
    tempo_map = TempoMap.constant(128.0)

    assert tempo_map.points == (TempoPoint(source_time=0.0, bpm=128.0),)
    assert tempo_map.bpm_at(0.0) == 128.0
    assert tempo_map.bpm_at(999.0) == 128.0
