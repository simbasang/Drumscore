import pytest

from app.benchmark import DEFAULT_MATCH_TOLERANCE_SECONDS, evaluate_corpus, evaluate_transcriber
from app.transcription import DrumEvent, DrumInstrument
from tests.fixtures.diagnostic_songs import DiagnosticSong, ExpectedHit


def _song(expected_hits: list[ExpectedHit], duration_seconds: float = 2.0) -> DiagnosticSong:
    return DiagnosticSong(
        key="test_song",
        description="test fixture",
        tempo_bpm=120.0,
        downbeat_offset_seconds=0.0,
        duration_seconds=duration_seconds,
        expected_hits=tuple(expected_hits),
    )


class FakeTranscriber:
    def __init__(self, events: list[DrumEvent]):
        self._events = events

    def transcribe(self, audio_path):
        return self._events


def test_evaluate_transcriber_counts_an_exact_time_match_as_a_true_positive():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.KICK)]
    )

    result = evaluate_transcriber(transcriber, song)

    kick_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.KICK)
    assert kick_metrics.true_positives == 1
    assert kick_metrics.false_positives == 0
    assert kick_metrics.false_negatives == 0
    assert kick_metrics.precision == 1.0
    assert kick_metrics.recall == 1.0
    assert kick_metrics.f1 == 1.0


def test_evaluate_transcriber_matches_within_tolerance():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.SNARE)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0 + DEFAULT_MATCH_TOLERANCE_SECONDS, instrument=DrumInstrument.SNARE)]
    )

    result = evaluate_transcriber(transcriber, song)

    snare_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.SNARE)
    assert snare_metrics.true_positives == 1
    assert snare_metrics.false_positives == 0
    assert snare_metrics.false_negatives == 0


def test_evaluate_transcriber_does_not_match_beyond_tolerance():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.SNARE)])
    transcriber = FakeTranscriber(
        [
            DrumEvent(
                id="e1",
                time=1.0 + DEFAULT_MATCH_TOLERANCE_SECONDS + 0.01,
                instrument=DrumInstrument.SNARE,
            )
        ]
    )

    result = evaluate_transcriber(transcriber, song)

    snare_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.SNARE)
    assert snare_metrics.true_positives == 0
    assert snare_metrics.false_positives == 1
    assert snare_metrics.false_negatives == 1


def test_evaluate_transcriber_counts_an_unmatched_prediction_as_a_false_positive():
    song = _song([])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.CRASH)]
    )

    result = evaluate_transcriber(transcriber, song)

    crash_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.CRASH)
    assert crash_metrics.false_positives == 1
    assert crash_metrics.precision == 0.0
    assert result.unmatched_predicted == (DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.CRASH),)


def test_evaluate_transcriber_counts_an_unmatched_expected_hit_as_a_false_negative():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.RIDE)])
    transcriber = FakeTranscriber([])

    result = evaluate_transcriber(transcriber, song)

    ride_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.RIDE)
    assert ride_metrics.false_negatives == 1
    assert ride_metrics.recall == 0.0
    assert result.unmatched_expected == (ExpectedHit(time=1.0, instrument=DrumInstrument.RIDE),)


def test_evaluate_transcriber_does_not_match_across_different_instruments():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.TOM_LOW)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.TOM_HIGH)]
    )

    result = evaluate_transcriber(transcriber, song)

    tom_low_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.TOM_LOW)
    tom_high_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.TOM_HIGH)
    assert tom_low_metrics.false_negatives == 1
    assert tom_high_metrics.false_positives == 1


def test_evaluate_transcriber_matches_the_closest_of_two_duplicate_predictions():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.HIHAT_CLOSED)])
    transcriber = FakeTranscriber(
        [
            DrumEvent(id="e1", time=1.01, instrument=DrumInstrument.HIHAT_CLOSED),
            DrumEvent(id="e2", time=1.03, instrument=DrumInstrument.HIHAT_CLOSED),
        ]
    )

    result = evaluate_transcriber(transcriber, song)

    hihat_metrics = next(
        m for m in result.per_instrument if m.instrument == DrumInstrument.HIHAT_CLOSED
    )
    assert hihat_metrics.true_positives == 1
    assert hihat_metrics.false_positives == 1
    assert result.unmatched_predicted == (
        DrumEvent(id="e2", time=1.03, instrument=DrumInstrument.HIHAT_CLOSED),
    )


def test_evaluate_corpus_returns_one_result_per_song_in_order():
    songs = [_song([]), _song([])]
    songs[0] = DiagnosticSong(**{**songs[0].__dict__, "key": "first"})
    songs[1] = DiagnosticSong(**{**songs[1].__dict__, "key": "second"})
    transcriber = FakeTranscriber([])

    results = evaluate_corpus(transcriber, songs)

    assert [r.song_key for r in results] == ["first", "second"]


def test_evaluate_transcriber_f1_is_zero_when_both_precision_and_recall_are_zero():
    song = _song([ExpectedHit(time=1.0, instrument=DrumInstrument.KICK)])
    transcriber = FakeTranscriber(
        [DrumEvent(id="e1", time=1.0, instrument=DrumInstrument.SNARE)]
    )

    result = evaluate_transcriber(transcriber, song)

    kick_metrics = next(m for m in result.per_instrument if m.instrument == DrumInstrument.KICK)
    assert kick_metrics.precision == 0.0
    assert kick_metrics.recall == 0.0
    assert kick_metrics.f1 == 0.0
