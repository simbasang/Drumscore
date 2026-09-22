# Post-processing and Strategy Selection (V1-016 / #49) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out GitHub issue #49 (V1-016) and Epic 3 (#30) by empirically investigating whether any benchmark-justified post-processing improves DrumScript's measured accuracy, and formally documenting the "keep DrumScript" production-strategy decision already implied by #47's evaluation.

**Architecture:** No production code changes. The investigation (already run by the plan's author, not left for the implementer to redo blind) found no post-processing opportunity that the corpus's actual false-positive/false-negative data justifies — this is the design's own pre-approved outcome: it explicitly said to implement a post-processing step only if the false-positive/negative pattern justifies one, with nothing assumed necessary in advance (per `docs/superpowers/specs/2026-09-22-transcription-engine-2-0-design.md`). This task's deliverable is therefore documentation: a new investigation write-up recording the evidence and the decision, plus a `TECHNICAL_DEBT.md` entry recording the specific limitation the investigation surfaced (the benchmark corpus's synthetic audio doesn't resemble real drum transients closely enough to meaningfully exercise DrumScript's physics classifier), so a future reader understands why the corpus's absolute F1 numbers are low without concluding DrumScript itself is broken.

**Tech Stack:** Documentation only. No code, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-22-transcription-engine-2-0-design.md` (section "#49 — Post-processing and strategy selection"), GitHub issue #49, `docs/transcription-engine-evaluation.md` (#47's recommendation, which this task formalizes into a strategy decision), `backend/tests/test_transcription_benchmark.py` (the recorded baseline this investigation is based on).

## Global Constraints

- Do not modify `drumscript`'s classification logic, `DrumScriptTranscriber`, `app/benchmark.py`, or the benchmark corpus in this task — the investigation already happened; this task documents its result.
- Do not fabricate a post-processing "improvement" to have something to ship — an honest "no change justified" outcome, backed by real data, is a complete and valid deliverable per the design's own stated fallback.
- `DrumScriptTranscriber` remains the production `DrumTranscriber` implementation (no engine swap — already established by #47's evidence-based evaluation).

---

## File Structure

- Create `docs/transcription-post-processing-investigation.md` — the empirical investigation write-up.
- Modify `TECHNICAL_DEBT.md` — new entry documenting the synthetic-corpus-realism limitation.

---

### Task 1: Document the post-processing investigation and the production-strategy decision

**Files:**
- Create: `docs/transcription-post-processing-investigation.md`
- Modify: `TECHNICAL_DEBT.md` (append a new entry)

**Interfaces:** None (documentation only; no code produced or consumed).

The investigation below was already run (not to be redone by the implementer) via `evaluate_corpus(DrumScriptTranscriber(), list_benchmark_songs())` (using `backend/app/benchmark.py` and `backend/tests/fixtures/benchmark_corpus.py`, both already committed) plus a follow-up script grouping each song's real predicted events by instrument to check specifically for near-duplicate same-instrument predictions within 50ms (the one post-processing candidate the design doc named by example). The exact real, observed results, to be transcribed faithfully into the new doc:

**Per-song false-positive/false-negative summary** (from `BenchmarkResult.unmatched_predicted`/`unmatched_expected`):

| Song | Predicted (total) | Expected (total) | Notable false-positive pattern | Notable false-negative pattern |
|---|---|---|---|---|
| `straight_rock` | 31 | 48 | Exclusively `hihat_closed`(3)/`hihat_open`(28) predicted | Zero `kick`, zero `snare` predicted despite both being expected throughout |
| `syncopated_funk` | 31 | 52 | `crash`(19)/`hihat_closed`(4)/`hihat_open`(8) | Zero `kick`, zero `snare` predicted |
| `double_kick` | 18 | 42 | `crash`(7)/`hihat_open`(7)/`ride`(3), only 1 `kick` predicted | Near-total miss on the song's defining fast kick pattern |
| `tom_fill_crash` | 1 | 12 | A single `crash` prediction total | Every kick and every tom in the fill went undetected |
| `ride_groove` | 67 | 48 | `crash`(45)/`hihat_closed`(8)/`hihat_open`(10)/`snare`(4) — the real ride pattern is being heard and classified as crash/hi-hat, not ride | Ride, kick, and snare all substantially under-detected |
| `full_kit_mixed` | 25 | 42 | `crash`(14)/`hihat_open`(7)/`hihat_closed`(3)/`snare`(1) | Kick and hi-hat-closed substantially under-detected |

**Near-duplicate check** (same-instrument predictions within 50ms of each other, per song): `straight_rock` 0, `syncopated_funk` 0, `double_kick` 0, `tom_fill_crash` 0 (only 1 prediction total), `ride_groove` 8 (5 in `crash`, 1 each in `hihat_closed`/`hihat_open`/`snare`), `full_kit_mixed` 0. Corpus-wide: 8 near-duplicate pairs out of 173 total predicted events (~4.6%), concentrated entirely in one song's `crash` predictions.

**Conclusion the investigation reached** (to be stated plainly in the new doc, not softened): DrumScript's real, measured failure mode on this synthetic corpus is **near-total non-detection or gross misclassification** of the corpus's purely-tonal instruments (kick's 60Hz sine, toms' 120/180/240Hz sines) and **systematic confusion between the corpus's noise-based instruments** (ride's real hits are overwhelmingly predicted as crash or hi-hat, not ride) — not a pattern of the same physical onset being detected twice. The one post-processing technique the design doc named as a candidate (duplicate-onset suppression) would therefore suppress almost nothing (8 pairs total, all inside one already-misclassified song) and would not address the actual failure mode (missing/misclassified instruments, not duplicated ones). No class-specific threshold retuning is in scope either, since that would mean modifying `drumscript`'s own internal classifier (explicitly out of scope for this project - see Global Constraints above and `docs/ARCHITECTURE_V1.md`'s statement that third-party engine internals never become project contracts). **No post-processing change is justified by this corpus's data.**

- [ ] **Step 1: Write the investigation doc**

Create `docs/transcription-post-processing-investigation.md`:

```markdown
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
```

- [ ] **Step 2: Add the TECHNICAL_DEBT.md entry**

Append to `TECHNICAL_DEBT.md`, after the existing last entry (from V1-011's work), with a `---` separator before it:

```markdown

---

## Benchmark corpus's synthetic audio doesn't exercise DrumScript's classifier realistically

**Found in:** V1-016 (#49) post-processing investigation

The Epic 3 benchmark corpus (`backend/tests/fixtures/benchmark_corpus.py`)
synthesizes each instrument as either a pure sine tone (kick, toms) or
white noise with an exponential decay envelope (snare, hi-hats, crash,
ride) - deliberately simple and copyright-free, following the existing
`diagnostic_songs.py` pattern. Running the real `DrumScriptTranscriber`
against this corpus (`backend/tests/test_transcription_benchmark.py`)
measured a corpus-wide F1 of only 0.0671, with near-total non-detection
of the sine-tone instruments (kick, toms) and systematic misclassification
among the noise-based instruments (e.g. `ride_groove`'s real ride pattern
is overwhelmingly predicted as crash or hi-hat-open instead of ride) - see
`docs/transcription-post-processing-investigation.md` for the full
per-song breakdown.

This number should not be read as "DrumScript is a poor transcriber" -
DrumScript's rule-based physics classifier (peak frequency, spectral
centroid, energy ratios, decay) was tuned against real drum recordings,
whose transients have broadband, non-stationary spectral content that a
clean sine tone or flat-spectrum noise burst doesn't reproduce. The
benchmark corpus is honest about measuring *this specific synthetic
corpus's* accuracy, which is what issues #45/#46 asked for, but it is not
a proxy for DrumScript's real-world accuracy on actual recordings.

**Fix would involve:** if a more realistic-audio benchmark becomes
valuable later (e.g. to more meaningfully evaluate post-processing
tweaks or a future candidate engine), synthesizing instrument sounds from
short real one-shot samples (licensed/royalty-free drum hit samples)
layered at known times, instead of pure sine/noise synthesis - preserving
the corpus's existing copyright-safety and determinism properties while
giving DrumScript's classifier real transient spectra to work with.

**Deferred:** out of scope for #49 - the corpus as built already satisfies
#45/#46's acceptance criteria (repeatable, labelled, documented tolerance,
multiple groove styles); this entry exists so a future reader doesn't
misread the low absolute F1 number as a DrumScript quality problem.
```

- [ ] **Step 3: Verify nothing else needs to change**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS, unchanged from before this task (this task touches no code, only documentation - this run is a sanity check that adding these two doc files didn't somehow break anything, e.g. via an accidental stray file inside `backend/`).

- [ ] **Step 4: Commit**

```bash
git add docs/transcription-post-processing-investigation.md TECHNICAL_DEBT.md
git commit -m "docs: document the post-processing investigation and v1.0 transcription strategy"
```

---

## Self-Review Notes

- **Spec coverage:** "Changes improve measured benchmark without unacceptable regressions" → satisfied vacuously and honestly: no changes were justified by the data, which is the design's own pre-approved fallback outcome, and the evidence for that call is fully documented. "thresholds/config are documented/tested" → N/A, no thresholds introduced. "raw events remain diagnosable" → unaffected, no code touched. "chosen engine remains behind DrumTranscriber" → true, `DrumScriptTranscriber` unchanged. "Epic 3 exit gate passes" → addressed in the new doc's "Strategy selection" section, cross-referencing #47's evaluation doc and the #45/#46 benchmark harness together.
- **Placeholder scan:** none — the investigation's real numbers are given verbatim (already measured by the plan's author before writing this plan, not left for the implementer to guess or re-derive).
- **Type consistency:** N/A (documentation-only task).
