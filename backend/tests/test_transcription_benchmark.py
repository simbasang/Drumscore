"""Records DrumScript's real, measured baseline accuracy against the
Epic 3 benchmark corpus (backend/tests/fixtures/benchmark_corpus.py).

This is a regression floor, not a target: the values below were the
actual measured result of running the real DrumScriptTranscriber against
the corpus at the time this test was written (see
docs/superpowers/plans/2026-09-22-benchmark-corpus-and-metrics.md, Task 4
for the original corpus-wide measurement procedure). If a future change to
DrumScript, the corpus, or post-processing legitimately changes these
numbers, update the baselines below deliberately (with a comment
explaining why) rather than loosening the margin to make a regression
pass.

The margin is relative (REGRESSION_MARGIN_RATIO), not absolute: at this
corpus's low baseline F1 (~0.07), a small absolute margin would swallow
the entire signal and the floor would never trip.

This test is slower than the rest of the suite (real audio synthesis +
a real DrumScript subprocess call per song) - kept in its own file so it
can be selected or skipped independently, and skipped automatically if
the drumscript_runner environment isn't set up (e.g. a fresh clone that
hasn't run `uv sync` inside backend/drumscript_runner yet).
"""

import pytest

from app.benchmark import evaluate_corpus
from app.drumscript_transcriber import DrumScriptTranscriber, runner_python
from app.transcription import DrumInstrument
from tests.fixtures.benchmark_corpus import list_benchmark_songs

# The real, measured baselines at the time this test was written - see
# the module docstring above for how these numbers were obtained.
BASELINE_CORPUS_F1 = 0.0671
BASELINE_PER_INSTRUMENT_F1 = {
    DrumInstrument.KICK: 0.0317,
    DrumInstrument.SNARE: 0.0488,
    DrumInstrument.HIHAT_CLOSED: 0.1143,
    DrumInstrument.HIHAT_OPEN: 0.0923,
    DrumInstrument.CRASH: 0.0674,
    DrumInstrument.RIDE: 0.0000,
    DrumInstrument.TOM_LOW: 0.0000,
    DrumInstrument.TOM_MID: 0.0000,
    DrumInstrument.TOM_HIGH: 0.0000,
}
REGRESSION_MARGIN_RATIO = 0.75

pytestmark = pytest.mark.skipif(
    not runner_python().exists(),
    reason="drumscript_runner environment not set up (run `uv sync` inside backend/drumscript_runner)",
)


def _corpus_wide_f1(results):
    total_tp = total_fp = total_fn = 0
    for result in results:
        for metrics in result.per_instrument:
            total_tp += metrics.true_positives
            total_fp += metrics.false_positives
            total_fn += metrics.false_negatives

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    return 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0


def _per_instrument_f1(results):
    totals = {instrument: {"tp": 0, "fp": 0, "fn": 0} for instrument in DrumInstrument}
    for result in results:
        for metrics in result.per_instrument:
            totals[metrics.instrument]["tp"] += metrics.true_positives
            totals[metrics.instrument]["fp"] += metrics.false_positives
            totals[metrics.instrument]["fn"] += metrics.false_negatives

    f1_by_instrument = {}
    for instrument, counts in totals.items():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_by_instrument[instrument] = (
            2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        )
    return f1_by_instrument


def test_drumscript_meets_its_recorded_baseline_on_the_benchmark_corpus():
    results = evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())

    f1 = _corpus_wide_f1(results)

    assert f1 >= BASELINE_CORPUS_F1 * REGRESSION_MARGIN_RATIO, (
        f"DrumScript's corpus-wide F1 ({f1:.4f}) dropped more than "
        f"{1 - REGRESSION_MARGIN_RATIO:.0%} below its recorded baseline "
        f"({BASELINE_CORPUS_F1}) - see this file's docstring."
    )


def test_drumscript_meets_its_recorded_per_instrument_baseline():
    results = evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())

    f1_by_instrument = _per_instrument_f1(results)

    for instrument, baseline in BASELINE_PER_INSTRUMENT_F1.items():
        f1 = f1_by_instrument[instrument]
        assert f1 >= baseline * REGRESSION_MARGIN_RATIO, (
            f"DrumScript's {instrument.value} F1 ({f1:.4f}) dropped more than "
            f"{1 - REGRESSION_MARGIN_RATIO:.0%} below its recorded baseline "
            f"({baseline}) - see this file's docstring."
        )


def test_evaluate_corpus_returns_a_result_for_every_benchmark_song():
    class _FakeTranscriber:
        def transcribe(self, audio_path):
            return []

    results = evaluate_corpus(_FakeTranscriber(), list_benchmark_songs())

    assert {r.song_key for r in results} == {s.key for s in list_benchmark_songs()}
