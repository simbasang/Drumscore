"""Records DrumScript's real, measured baseline accuracy against the
Epic 3 benchmark corpus (backend/tests/fixtures/benchmark_corpus.py).

This is a regression floor, not a target: the corpus-wide F1 value below
was the actual measured result of running the real DrumScriptTranscriber
against the corpus at the time this test was written (see
docs/superpowers/plans/2026-09-22-benchmark-corpus-and-metrics.md, Task 4
for the exact procedure used to obtain it). If a future change to
DrumScript, the corpus, or post-processing legitimately changes this
number, update BASELINE_CORPUS_F1 deliberately (with a comment explaining
why) rather than loosening the margin below to make a regression pass.

This test is slower than the rest of the suite (real audio synthesis +
a real DrumScript subprocess call per song) - kept in its own file so it
can be selected or skipped independently if that proves necessary.
"""

from app.benchmark import evaluate_corpus
from app.drumscript_transcriber import DrumScriptTranscriber
from tests.fixtures.benchmark_corpus import list_benchmark_songs

# The real, measured corpus-wide F1 at the time this test was written -
# see the module docstring above for how this number was obtained.
BASELINE_CORPUS_F1 = 0.0671
REGRESSION_MARGIN = 0.05


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


def test_drumscript_meets_its_recorded_baseline_on_the_benchmark_corpus():
    results = evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())

    f1 = _corpus_wide_f1(results)

    assert f1 >= BASELINE_CORPUS_F1 - REGRESSION_MARGIN, (
        f"DrumScript's corpus-wide F1 ({f1:.4f}) dropped more than "
        f"{REGRESSION_MARGIN} below its recorded baseline "
        f"({BASELINE_CORPUS_F1}) - see this file's docstring."
    )


def test_evaluate_corpus_returns_a_result_for_every_benchmark_song():
    results = evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())

    assert {r.song_key for r in results} == {s.key for s in list_benchmark_songs()}
