import pytest

from app.transcription import DrumInstrument
from tests.fixtures.benchmark_corpus import (
    get_benchmark_song,
    list_benchmark_songs,
)


def test_list_benchmark_songs_returns_six_songs():
    songs = list_benchmark_songs()

    assert len(songs) == 6


def test_list_benchmark_songs_has_unique_keys():
    songs = list_benchmark_songs()

    keys = [song.key for song in songs]
    assert len(keys) == len(set(keys))


def test_get_benchmark_song_raises_key_error_for_unknown_key():
    with pytest.raises(KeyError, match="Unknown benchmark song fixture"):
        get_benchmark_song("does_not_exist")


def test_get_benchmark_song_returns_the_matching_song():
    song = get_benchmark_song("straight_rock")

    assert song.key == "straight_rock"


def test_every_expected_hit_time_is_within_the_songs_duration():
    for song in list_benchmark_songs():
        for hit in song.expected_hits:
            assert 0.0 <= hit.time < song.duration_seconds, (
                f"{song.key}: hit at {hit.time}s exceeds duration {song.duration_seconds}s"
            )


def test_every_expected_hit_time_is_non_negative():
    for song in list_benchmark_songs():
        for hit in song.expected_hits:
            assert hit.time >= 0.0


def test_every_song_has_at_least_one_expected_hit():
    for song in list_benchmark_songs():
        assert len(song.expected_hits) > 0, f"{song.key} has no expected hits"


def test_corpus_covers_every_drum_instrument_at_least_once():
    covered_instruments = {
        hit.instrument for song in list_benchmark_songs() for hit in song.expected_hits
    }

    assert covered_instruments == set(DrumInstrument)


def test_full_kit_mixed_song_alone_covers_every_drum_instrument():
    song = get_benchmark_song("full_kit_mixed")

    covered_instruments = {hit.instrument for hit in song.expected_hits}
    assert covered_instruments == set(DrumInstrument)


def test_generate_audio_produces_nonempty_audio_for_every_song():
    for song in list_benchmark_songs():
        audio = song.generate_audio()
        assert len(audio) > 0
