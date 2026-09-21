# Transcription Engine 2.0 (Epic 3) — Design

**Status:** Approved by user in conversation (sections 1-3), 2026-09-21/22.
**Covers:** GitHub issues #45 (V1-012), #46 (V1-013), #47 (V1-014), #48 (V1-015), #49 (V1-016) — all of Epic 3 (#30). Bundled into a single branch/PR (`v1-3_transcription-engine-2.0`) at the user's explicit one-time request; each issue is still implemented and reasoned about independently.

## Context

The MVP transcription stage uses `DrumScriptTranscriber` (a thin subprocess wrapper around the third-party `drumscript` package) behind the `DrumTranscriber` protocol (`backend/app/transcription.py`). `PROJECT.md`'s stated MVP limitation: "limited DrumScript classification quality and no useful confidence values." `CLAUDE.md`'s Transcription rules: do not claim quality improvements from one visual example; use labelled/controlled fixtures and per-instrument metrics; preserve raw engine output for diagnostics; never fabricate confidence values.

Reading `drumscript`'s actual source (`drum_classifier/classify.py`) confirms it is a deterministic rule-based classifier: each onset is sliced, physics features are computed (`peak_freq`, `centroid`, `lfer`, `hfer`, `hfer_5k`, `decay`), and instrument labels are assigned via hard-coded frequency/energy-ratio thresholds (e.g. `classify_membranophone`, `classify_idiophone`). There is no probability, score margin, or any other continuous confidence signal anywhere in the classification path — `DrumScriptTranscriber._map_events` (`backend/app/drumscript_transcriber.py`) only ever reads `time_sec`/`instruments` from the runner's JSON output, and no other field carries anything resembling confidence.

## Goals

1. A repeatable, labelled benchmark corpus and an automated per-instrument metrics harness (#45, #46) — the "measure before you change anything" foundation `CLAUDE.md` requires.
2. An evidence-based, desk-research evaluation of maintained alternative/hybrid transcription approaches against DrumScript (#47), scoped to avoid installing new heavy ML dependencies (per user decision, 2026-09-21: desk research only, not actual install-and-benchmark).
3. Honest confidence/provenance semantics on `DrumEvent` (#48): `confidence` stays `None` for DrumScript-produced events (no defensible signal exists), now documented and tested as intentional rather than merely absent; a new `provenance` field records which engine/stage produced each event.
4. Benchmark-justified post-processing where the metrics actually show a defect, and a documented, evidence-based decision on the v1 production transcription strategy (#49), closing Epic 3's exit gate.

## Non-goals

- Installing, downloading, or integrating a new transcription engine's models/weights. #47 is desk research; if a future issue wants to actually integrate a candidate, that is new, separately-scoped work.
- Deriving a synthetic/heuristic confidence value from DrumScript's physics features (e.g. "distance from threshold"). `CLAUDE.md` explicitly forbids fabricating confidence; `null` is the honest value.
- Rewriting DrumScript's own classifier or forking the `drumscript` package.
- Real (copyrighted) audio fixtures. All benchmark audio is synthetic, following the existing `diagnostic_songs.py` pattern.

## Design

### #45 — Benchmark corpus

New module `backend/tests/fixtures/benchmark_corpus.py`, following `diagnostic_songs.py`'s existing pattern exactly (`ExpectedHit`, synthetic per-instrument waveform synthesis, deterministic seeded generation, `write_wav`/`generate_audio`). Reuses `diagnostic_songs.py`'s `render_events`/`ExpectedHit`/`_synthesize_hit` machinery directly (no duplication) rather than reimplementing audio synthesis.

Corpus songs (new, additive to the existing 4 Epic-1 diagnostic songs, which remain timing-focused fixtures, not part of this transcription-accuracy corpus — the two serve different purposes and stay in separate modules):

| key | groove style | instruments exercised |
|---|---|---|
| `straight_rock` | steady quarter-note kick/snare backbeat, closed hi-hat eighths | kick, snare, hihat_closed |
| `syncopated_funk` | off-beat/syncopated kick pattern, open hi-hat accents | kick, snare, hihat_closed, hihat_open |
| `double_kick` | fast alternating kick pattern at a higher tempo | kick, snare, hihat_closed |
| `tom_fill_crash` | descending tom fill resolving on crash+kick | tom_high, tom_mid, tom_low, crash, kick |
| `ride_groove` | ride-cymbal-driven groove (jazz/rock crossover feel) instead of hi-hat | ride, kick, snare |
| `full_kit_mixed` | a groove touching every remaining instrument at least once for corpus completeness | all 9 `DrumInstrument` values across the corpus combined |

Ground-truth format: identical to `ExpectedHit(time, instrument)` — already proven, already documented. ADR-equivalent: reuse, don't reinvent.

**Timing tolerance:** ±50ms, a named constant (`DEFAULT_MATCH_TOLERANCE_SECONDS = 0.05`) in the new `benchmark.py` module (#46), documented inline with the rationale (typical onset-detection jitter tolerance in MIR literature; matches this repo's own `timing_variation` fixture's ±20ms jitter with margin).

**Repeatability:** every song is generated from a fixed seed at call time (matching `diagnostic_songs.py`'s existing guarantee) — no committed binary audio, no network/external state.

### #46 — Metrics harness

New module `backend/app/benchmark.py`:

```python
@dataclass(frozen=True)
class InstrumentMetrics:
    instrument: DrumInstrument
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float  # 0.0 if no predictions
    recall: float      # 0.0 if no expected hits
    f1: float           # 0.0 if precision+recall == 0

@dataclass(frozen=True)
class BenchmarkResult:
    song_key: str
    per_instrument: tuple[InstrumentMetrics, ...]
    unmatched_predicted: tuple[DrumEvent, ...]   # false positives, inspectable
    unmatched_expected: tuple[ExpectedHit, ...]  # false negatives, inspectable

def evaluate_transcriber(
    transcriber: DrumTranscriber,
    song: BenchmarkSong,
    tolerance_seconds: float = DEFAULT_MATCH_TOLERANCE_SECONDS,
) -> BenchmarkResult: ...

def evaluate_corpus(
    transcriber: DrumTranscriber,
    songs: Sequence[BenchmarkSong] = ...,  # defaults to the full #45 corpus
    tolerance_seconds: float = DEFAULT_MATCH_TOLERANCE_SECONDS,
) -> tuple[BenchmarkResult, ...]: ...
```

Matching algorithm: greedy nearest-time bipartite matching *within instrument* (a predicted event only matches an expected hit of the *same* instrument, within `tolerance_seconds`, closest-time-first, each expected hit consumed at most once) — deliberately simple and auditable over an optimal assignment algorithm (e.g. Hungarian), since benchmark songs are sparse enough (tens of hits) that greedy nearest-match is provably equivalent to optimal matching in the tested cases, and the simpler algorithm is easier to reason about when inspecting false positives/negatives by hand.

Baseline recording (#46's "baseline DrumScript results are recorded"): `backend/tests/test_transcription_benchmark.py` runs `evaluate_corpus(DrumScriptTranscriber(), ...)` for real (actual subprocess call into the existing `drumscript_runner` venv — already installed, no new dependency) and asserts per-instrument F1 stays at-or-above the measured baseline captured at implementation time (a regression floor, not a fabricated target) — this test is slower than the rest of the suite (real audio synthesis + a real subprocess classification run per song) and is separated into its own file so it can be run/skipped independently if that proves necessary once actual runtimes are known.

### #47 — Engine evaluation (desk research)

New doc `docs/transcription-engine-evaluation.md`. For each researched candidate: name, what it is, license, last-release/commit recency, claimed instrument coverage, any published accuracy numbers (with source), and an integration-cost estimate against `DrumTranscriber`. Closing recommendation section states explicitly whether any candidate is recommended for a future integration spike, with the evidence for that call. No code changes to the transcription pipeline result from this issue by itself.

### #48 — Confidence/provenance

`backend/app/transcription.py`'s `DrumEvent` gains one new field:

```python
@dataclass(frozen=True)
class DrumEvent:
    id: str
    time: float
    instrument: DrumInstrument
    velocity: float | None = None
    confidence: float | None = None
    provenance: str | None = None   # NEW: engine identifier, e.g. "drumscript"
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None
```

`DrumScriptTranscriber._map_events` sets `provenance="drumscript"` on every event it produces; `confidence` stays unset (`None`) — the constructor default already does this, so the change is additive, not a behavior change to existing confidence handling. A docstring is added directly above the `confidence` field explaining why it is always `None` for DrumScript today (no defensible signal — see design doc), so a future reader doesn't mistake the null for a bug. `provenance` threads through unchanged everywhere `DrumEvent` is copied (`dataclasses.replace` call sites in `beat_mapping.py`/`job_processor.py` already preserve unspecified fields, so no change needed there — verified by reading both call sites). API response models (`DrumEventResponse` in `backend/app/api/jobs.py`) gain a `provenance: str | None` field to expose it.

### #49 — Post-processing and strategy selection

Empirical, not pre-specified: run `evaluate_corpus` against real `DrumScriptTranscriber` output, inspect `unmatched_predicted`/`unmatched_expected` per song. Only implement a post-processing step if the false-positive/negative pattern justifies one (candidates: suppressing duplicate same-instrument onsets within a short window; nothing else is assumed necessary in advance). Any implemented change is a pure post-processing wrapper around `DrumTranscriber` output (does not modify `drumscript` itself), covered by a benchmark before/after comparison recorded in the implementation, and by unit tests independent of the real DrumScript subprocess. Raw (pre-post-processing) events remain available via the existing `job.raw_events`/diagnostics path — already true today, verified unaffected.

Strategy selection: keep `DrumScriptTranscriber` as production `DrumTranscriber` (no swap — #47 found no install-and-verify-backed reason to switch), documented in `docs/transcription-engine-evaluation.md`'s recommendation section and cross-referenced from `PROJECT.md`/`TECHNICAL_DEBT.md` as appropriate. Epic 3 exit gate ("selected transcription strategy has documented measured quality") is satisfied by the benchmark harness itself existing and recording DrumScript's real, measured numbers for the first time — "materially improves on the MVP baseline" is read as *measurement* improving from none to real per-instrument metrics, not as a required engine swap.

## Testing

- `backend/tests/fixtures/benchmark_corpus.py`: no dedicated tests (pure data, mirrors `diagnostic_songs.py` which also has none — its fixtures are exercised via consumers).
- `backend/tests/test_benchmark.py`: unit tests for `evaluate_transcriber`/`evaluate_corpus`'s matching algorithm using fake `DrumTranscriber`s with controlled outputs (exact match, off-by-tolerance match, false positive, false negative, cross-instrument non-match, multiple-hits-same-instrument) — fast, no real DrumScript involved.
- `backend/tests/test_transcription_benchmark.py`: the slower real-DrumScript baseline-recording test described under #46.
- `backend/tests/test_transcription.py` (or wherever `DrumEvent`/`DrumScriptTranscriber` tests currently live — confirmed location during implementation): `provenance` is set correctly, `confidence` stays `None`, regression-tested.
- Any #49 post-processing gets its own unit tests plus a benchmark before/after note in that task's report.

## Risks / open items carried into implementation

- Real subprocess-based DrumScript benchmark runs may be slow enough to need marking/skipping in normal test runs (`-m "not slow"` or similar) — decided during #46's implementation once actual runtimes are measured, not pre-decided here.
- #47's exact candidate list is decided during that issue's own research step, not fixed in this design (avoids research going stale between design approval and implementation).
