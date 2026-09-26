import io

import pytest

from app.tempo_benchmark import (
    REAL_TEMPO_SONGS,
    TempoFixture,
    classify_tempo,
    evaluate,
    fetch_stems,
    run_benchmark,
)
from app.youtube_source import YouTubeSourceValidator
from tests.fakes import FOUR_BEATS, FakeBeatDetector, FakeExtractor, FakeSeparator

SONG = TempoFixture(video_id="abcdefghijk", title="Song", reference_bpm=120.0, meter="4/4", sources="test")


@pytest.mark.parametrize(
    "detected, verdict",
    [
        (120.0, "correct"),
        (124.8, "correct"),
        (115.2, "correct"),
        (125.5, "other"),
        (240.0, "double"),
        (60.0, "half"),
        (180.0, "three_halves"),
        (80.0, "two_thirds"),
        (100.0, "other"),
    ],
)
def test_classify_tempo_names_the_pulse_level_error(detected, verdict):
    result = classify_tempo(detected, reference=120.0)

    assert result == verdict


def test_evaluate_reports_songs_without_stems_as_missing():
    results = evaluate([SONG], lambda fixture: None)

    assert (results[0].detected_bpm, results[0].verdict) == (None, "missing")


def test_evaluate_classifies_each_detected_tempo():
    results = evaluate([SONG], lambda fixture: 239.0)

    assert (results[0].detected_bpm, results[0].verdict) == (239.0, "double")


def test_real_tempo_songs_lists_eight_distinct_songs_with_references():
    ids = [song.video_id for song in REAL_TEMPO_SONGS]

    assert len(set(ids)) == 8
    assert all(song.reference_bpm > 0 for song in REAL_TEMPO_SONGS)


def test_fetch_stems_stores_both_stems_per_song(tmp_path):
    fetch_stems([SONG], tmp_path, YouTubeSourceValidator(), FakeExtractor(), FakeSeparator())

    song_dir = tmp_path / SONG.video_id
    assert (song_dir / "drums.wav").read_bytes() == b"fake drums"
    assert (song_dir / "accompaniment.wav").read_bytes() == b"fake accompaniment"


def test_fetch_stems_skips_songs_that_already_have_stems(tmp_path):
    song_dir = tmp_path / SONG.video_id
    song_dir.mkdir()
    (song_dir / "drums.wav").write_bytes(b"kept")
    (song_dir / "accompaniment.wav").write_bytes(b"kept")

    fetch_stems([SONG], tmp_path, YouTubeSourceValidator(), FakeExtractor(error=RuntimeError("no")), FakeSeparator())

    assert (song_dir / "drums.wav").read_bytes() == b"kept"


def _with_stems(tmp_path):
    song_dir = tmp_path / SONG.video_id
    song_dir.mkdir()
    (song_dir / "drums.wav").write_bytes(b"")
    (song_dir / "accompaniment.wav").write_bytes(b"")


def test_run_benchmark_passes_when_every_tempo_is_correct(tmp_path):
    _with_stems(tmp_path)
    out = io.StringIO()

    status = run_benchmark([SONG], tmp_path, FakeBeatDetector(FOUR_BEATS), out)

    assert status == 0
    assert SONG.video_id in out.getvalue()
    assert "correct" in out.getvalue()


def test_run_benchmark_fails_when_a_song_is_missing(tmp_path):
    out = io.StringIO()

    status = run_benchmark([SONG], tmp_path, FakeBeatDetector(FOUR_BEATS), out)

    assert status == 1
    assert "missing" in out.getvalue()
