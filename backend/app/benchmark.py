import dataclasses
import tempfile
from pathlib import Path
from typing import Protocol, Sequence

from app.transcription import DrumEvent, DrumInstrument, DrumTranscriber

# Typical onset-detection jitter tolerance in MIR literature; also matches
# this repo's own timing_variation fixture's +/-20ms jitter with margin.
DEFAULT_MATCH_TOLERANCE_SECONDS = 0.05


class ExpectedHit(Protocol):
    """Structural match for tests.fixtures.diagnostic_songs.ExpectedHit -
    this module must not import from tests/ (app/ is the deployed
    package and tests/fixtures pulls in dev-only dependencies like
    soundfile). Any object with these two attributes satisfies this
    protocol automatically."""

    time: float
    instrument: DrumInstrument


class BenchmarkSong(Protocol):
    """Structural match for tests.fixtures.diagnostic_songs.DiagnosticSong
    (and tests.fixtures.benchmark_corpus's songs, which share the same
    shape) - see ExpectedHit's docstring for why this is a Protocol
    instead of an import."""

    key: str
    expected_hits: Sequence[ExpectedHit]

    def write_wav(self, path: Path) -> Path: ...


@dataclasses.dataclass(frozen=True)
class InstrumentMetrics:
    instrument: DrumInstrument
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


@dataclasses.dataclass(frozen=True)
class BenchmarkResult:
    song_key: str
    per_instrument: tuple[InstrumentMetrics, ...]
    unmatched_predicted: tuple[DrumEvent, ...]
    unmatched_expected: tuple[ExpectedHit, ...]


def _match_instrument(
    predicted: list[DrumEvent],
    expected: list[ExpectedHit],
    tolerance_seconds: float,
) -> tuple[int, list[DrumEvent], list[ExpectedHit]]:
    """Greedy nearest-time matching within a single instrument: each
    predicted event (processed in time order) is matched to its closest
    still-unmatched expected hit within tolerance_seconds. When two
    predicted events could both match the same expected hit, the
    earlier-in-time predicted event is processed first and claims it,
    even if a later-processed predicted event would have been numerically
    closer - simple and auditable rather than an optimal assignment
    algorithm, sufficient for this corpus's sparse (tens of hits) songs
    where this doesn't change true/false-positive counts in practice.
    Returns (true_positive_count, unmatched_predicted, unmatched_expected)."""
    remaining_expected = list(expected)
    unmatched_predicted: list[DrumEvent] = []
    true_positives = 0

    for event in sorted(predicted, key=lambda e: e.time):
        best_index = None
        best_distance = None
        for index, hit in enumerate(remaining_expected):
            distance = abs(event.time - hit.time)
            # Add small epsilon (1e-9) to handle floating point precision when distance equals tolerance
            if distance <= tolerance_seconds + 1e-9 and (best_distance is None or distance < best_distance):
                best_index = index
                best_distance = distance

        if best_index is None:
            unmatched_predicted.append(event)
        else:
            remaining_expected.pop(best_index)
            true_positives += 1

    return true_positives, unmatched_predicted, remaining_expected


def evaluate_transcriber(
    transcriber: DrumTranscriber,
    song: BenchmarkSong,
    tolerance_seconds: float = DEFAULT_MATCH_TOLERANCE_SECONDS,
) -> BenchmarkResult:
    """Synthesizes song's audio, runs it through transcriber, and scores
    the result against song's ground truth per instrument."""
    with tempfile.TemporaryDirectory() as scratch_dir:
        audio_path = Path(scratch_dir) / f"{song.key}.wav"
        song.write_wav(audio_path)
        predicted_events = transcriber.transcribe(audio_path)

    per_instrument: list[InstrumentMetrics] = []
    all_unmatched_predicted: list[DrumEvent] = []
    all_unmatched_expected: list[ExpectedHit] = []

    for instrument in DrumInstrument:
        predicted_for_instrument = [e for e in predicted_events if e.instrument == instrument]
        expected_for_instrument = [h for h in song.expected_hits if h.instrument == instrument]

        true_positives, unmatched_predicted, unmatched_expected = _match_instrument(
            predicted_for_instrument, expected_for_instrument, tolerance_seconds
        )
        false_positives = len(unmatched_predicted)
        false_negatives = len(unmatched_expected)

        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives) > 0
            else 0.0
        )
        recall = (
            true_positives / (true_positives + false_negatives)
            if (true_positives + false_negatives) > 0
            else 0.0
        )
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        per_instrument.append(
            InstrumentMetrics(
                instrument=instrument,
                true_positives=true_positives,
                false_positives=false_positives,
                false_negatives=false_negatives,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
        all_unmatched_predicted.extend(unmatched_predicted)
        all_unmatched_expected.extend(unmatched_expected)

    return BenchmarkResult(
        song_key=song.key,
        per_instrument=tuple(per_instrument),
        unmatched_predicted=tuple(sorted(all_unmatched_predicted, key=lambda e: e.time)),
        unmatched_expected=tuple(sorted(all_unmatched_expected, key=lambda h: h.time)),
    )


def evaluate_corpus(
    transcriber: DrumTranscriber,
    songs: Sequence[BenchmarkSong],
    tolerance_seconds: float = DEFAULT_MATCH_TOLERANCE_SECONDS,
) -> tuple[BenchmarkResult, ...]:
    return tuple(evaluate_transcriber(transcriber, song, tolerance_seconds) for song in songs)
