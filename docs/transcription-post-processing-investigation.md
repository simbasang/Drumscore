# Post-processing Investigation and Strategy Selection (Issue #49, V1-016)

## What was investigated

Per the Epic 3 design doc's empirical approach (`docs/superpowers/specs/2026-09-22-transcription-engine-2-0-design.md`,
"#49 — Post-processing and strategy selection"), this issue runs the
#45/#46 benchmark harness against the real `DrumScriptTranscriber`,
inspects the false-positive/false-negative breakdown per song, and
implements a post-processing step ONLY if the data justifies one. No
tweak is pre-assumed necessary.

## What the data showed

Per-song results from `evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())`
(the same real run recorded as the baseline in
`backend/tests/test_transcription_benchmark.py`, BASELINE_CORPUS_F1 = 0.0671):

| Song | Predicted (total) | Expected (total) | Notable false-positive pattern | Notable false-negative pattern |
|---|---|---|---|---|
| `straight_rock` | 31 | 48 | Exclusively hihat_closed(3)/hihat_open(28) predicted | Zero kick, zero snare predicted despite both being expected throughout |
| `syncopated_funk` | 31 | 52 | crash(19)/hihat_closed(4)/hihat_open(8) | Zero kick, zero snare predicted |
| `double_kick` | 18 | 42 | crash(7)/hihat_open(7)/ride(3), only 1 kick predicted | Near-total miss on the song's defining fast kick pattern |
| `tom_fill_crash` | 1 | 12 | A single crash prediction total | Every kick and every tom in the fill went undetected |
| `ride_groove` | 67 | 48 | crash(45)/hihat_closed(8)/hihat_open(10)/snare(4) - the real ride pattern is heard and classified as crash/hi-hat, not ride | Ride, kick, and snare all substantially under-detected |
| `full_kit_mixed` | 25 | 42 | crash(14)/hihat_open(7)/hihat_closed(3)/snare(1) | Kick and hi-hat-closed substantially under-detected |

**Duplicate-prediction check** (the one post-processing candidate the
design doc named by example - same-instrument predictions within 50ms
of each other): 8 near-duplicate pairs across the entire corpus's 173
total predicted events (~4.6%), all 8 concentrated in `ride_groove`'s
already-misclassified `crash` predictions. No other song has any.

## Conclusion

DrumScript's real failure mode on this synthetic corpus is **near-total
non-detection or gross misclassification** of the corpus's purely-tonal
instruments (kick, toms - synthesized as sine tones) and **systematic
confusion between the corpus's noise-based instruments** (the real ride
pattern in `ride_groove` is overwhelmingly predicted as crash or
hi-hat-open, not ride) - not a pattern of the same physical onset being
detected twice.

Duplicate-onset suppression, the specific technique the design doc named
as a candidate, would therefore suppress almost nothing (8 pairs, all
inside one already-misclassified song) and would not address the actual
failure mode. Class-specific threshold retuning is also not in scope:
that would mean modifying `drumscript`'s own internal classifier
thresholds, which is a third-party engine's internals and never becomes
this project's contract (`docs/ARCHITECTURE_V1.md`).

**No post-processing change is justified by this corpus's data.** This
is the design doc's own explicitly-anticipated legitimate outcome: "If
nothing in the corpus reveals a clear, justified tweak, the honest
outcome is 'no post-processing needed at this corpus size.'"

See `TECHNICAL_DEBT.md`'s "Benchmark corpus's synthetic audio doesn't
exercise DrumScript's classifier realistically" entry for the corpus
side of this finding - it's the benchmark's synthetic audio, not
DrumScript's real-world quality, that this investigation's low numbers
actually reflect.

## Strategy selection

Combined with issue #47's evidence-based evaluation
(`docs/transcription-engine-evaluation.md`, "no candidate is recommended
for a future integration spike at this time"), the v1.0 production
transcription strategy is: **`DrumScriptTranscriber` remains the
production `DrumTranscriber` implementation, unchanged, with no
post-processing wrapper added.**

This satisfies Epic 3's exit gate ("selected transcription strategy has
documented measured quality") - for the first time, DrumScript's
accuracy is measured and documented via a real, repeatable benchmark
(`backend/app/benchmark.py`, `backend/tests/fixtures/benchmark_corpus.py`,
`backend/tests/test_transcription_benchmark.py`) rather than judged by
eye from a single example, satisfying `CLAUDE.md`'s "do not claim
quality improvements from one visual example" rule. "Materially
improves on the MVP baseline" is met by this measurement capability
itself existing for the first time, not by an engine swap - consistent
with the design decision made and approved before implementation began
(`docs/superpowers/specs/2026-09-22-transcription-engine-2-0-design.md`,
"Epic 3 exit gate... is satisfied by the benchmark harness itself
existing").
