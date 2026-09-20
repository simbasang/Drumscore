from collections import Counter

import numpy as np
import pytest
import soundfile as sf

from app.transcription import DrumInstrument
from tests.fixtures.diagnostic_songs import (
    DiagnosticSong,
    ExpectedHit,
    get_diagnostic_song,
    list_diagnostic_songs,
    render_events,
)


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


def test_diagnostic_song_generate_audio_matches_declared_duration():
    song = DiagnosticSong(
        key="test",
        description="test fixture",
        tempo_bpm=120.0,
        downbeat_offset_seconds=0.0,
        duration_seconds=1.0,
        expected_hits=(ExpectedHit(time=0.0, instrument=DrumInstrument.KICK),),
    )

    audio = song.generate_audio()

    assert len(audio) == int(round(1.0 * song.sample_rate))


def test_diagnostic_song_write_wav_produces_a_readable_file_of_matching_length(tmp_path):
    song = DiagnosticSong(
        key="test",
        description="test fixture",
        tempo_bpm=120.0,
        downbeat_offset_seconds=0.0,
        duration_seconds=1.0,
        expected_hits=(ExpectedHit(time=0.0, instrument=DrumInstrument.KICK),),
    )
    wav_path = tmp_path / "song.wav"

    song.write_wav(wav_path)
    audio, sample_rate = sf.read(str(wav_path))

    assert sample_rate == song.sample_rate
    assert len(audio) == len(song.generate_audio())


def test_get_diagnostic_song_raises_for_an_unknown_key():
    with pytest.raises(KeyError):
        get_diagnostic_song("not_a_real_fixture")


def test_steady_4_4_has_its_first_downbeat_at_time_zero():
    song = get_diagnostic_song("steady_4_4")

    assert song.downbeat_offset_seconds == 0.0
    assert song.expected_hits[0].time == 0.0
    assert song.tempo_bpm == 120.0


def test_steady_4_4_expected_hits_are_sorted_and_within_duration():
    song = get_diagnostic_song("steady_4_4")

    times = [hit.time for hit in song.expected_hits]

    assert times == sorted(times)
    assert all(0.0 <= t < song.duration_seconds for t in times)


def test_intro_count_in_places_the_first_downbeat_after_a_count_in():
    song = get_diagnostic_song("intro_count_in")

    assert song.downbeat_offset_seconds > 0.0
    assert song.expected_hits[0].time == pytest.approx(0.5)
    assert any(
        hit.time == pytest.approx(song.downbeat_offset_seconds)
        and hit.instrument == DrumInstrument.KICK
        for hit in song.expected_hits
    )


def test_list_diagnostic_songs_includes_steady_4_4_and_intro_count_in():
    keys = {song.key for song in list_diagnostic_songs()}

    assert {"steady_4_4", "intro_count_in"}.issubset(keys)


REQUIRED_KEYS = {"steady_4_4", "intro_count_in", "dense_fill", "timing_variation"}


def test_list_diagnostic_songs_covers_all_required_timing_cases():
    keys = {song.key for song in list_diagnostic_songs()}

    assert keys == REQUIRED_KEYS


@pytest.mark.parametrize("key", sorted(REQUIRED_KEYS))
def test_every_fixture_expected_hits_are_sorted_and_within_duration(key):
    song = get_diagnostic_song(key)

    times = [hit.time for hit in song.expected_hits]

    assert times == sorted(times)
    assert all(0.0 <= t < song.duration_seconds for t in times)


@pytest.mark.parametrize("key", sorted(REQUIRED_KEYS))
def test_every_fixture_generates_deterministic_audio(key):
    song = get_diagnostic_song(key)

    first = song.generate_audio()
    second = song.generate_audio()

    np.testing.assert_array_equal(first, second)


def test_dense_fill_has_a_measure_with_more_hits_than_the_groove_measures():
    song = get_diagnostic_song("dense_fill")
    seconds_per_beat = 60.0 / song.tempo_bpm
    measure_seconds = 4 * seconds_per_beat

    hits_per_measure: dict[int, int] = {}
    for hit in song.expected_hits:
        measure_index = int(hit.time // measure_seconds)
        hits_per_measure[measure_index] = hits_per_measure.get(measure_index, 0) + 1

    groove_measure_counts = [hits_per_measure[0], hits_per_measure[1]]
    fill_measure_count = hits_per_measure[2]

    assert fill_measure_count > max(groove_measure_counts)


def test_timing_variation_deviates_from_a_perfect_grid():
    song = get_diagnostic_song("timing_variation")
    seconds_per_sixteenth = (60.0 / song.tempo_bpm) / 4

    on_grid_hits = sum(
        1
        for hit in song.expected_hits
        if abs((hit.time / seconds_per_sixteenth) - round(hit.time / seconds_per_sixteenth))
        < 1e-6
    )

    assert on_grid_hits < len(song.expected_hits)


def test_timing_variation_has_the_same_instrument_counts_as_steady_4_4():
    # Jitter can reorder hits that share a nominal time (e.g. a kick and a
    # hi-hat on the same beat swapping order under +/-20ms human timing),
    # so exact sequence isn't preserved - only the multiset of instruments is.
    steady = get_diagnostic_song("steady_4_4")
    varied = get_diagnostic_song("timing_variation")

    assert Counter(h.instrument for h in steady.expected_hits) == Counter(
        h.instrument for h in varied.expected_hits
    )
