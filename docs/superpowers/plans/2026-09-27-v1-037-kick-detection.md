# V1-037 — Kick detection on real recordings (#114)

**Goal:** usable kick recall on real recordings, measured on labelled real audio, without touching snare/hi-hat output. Blocks #86.

## Root cause (measured 2026-09-27, scratch spike)

DrumScript's onset detector finds the kicks; its classifier throws them away.

- `classify_events` (installed `drumscript/drum_classifier/classify.py:407`) labels an onset "kick" only if `lfer >= 0.32` (share of the mean magnitude spectrum ≤150 Hz over a 200 ms slice) **and** peak frequency in 40–140 Hz. On a real drum stem, hats/snare/cymbal ringing over the kick dilute the whole-spectrum ratio.
- MDB Drums, drum-only tracks: an onset exists within 50 ms of 100% / 100% / 90% of labelled kicks (80sRock / Britpop / Punk), but only 15/63, 19/48, 12/73 are classified kick. Median `lfer` at real kicks 0.22–0.32.
- CCR drum stem (Demucs): 555 onsets, 17 kicks vs 263 in the reference MIDI; `lfer` p99 over all onsets is 0.38, so the rule almost never fires. Kick F1 0.09.
- Spike: a low-band (30–150 Hz) log-energy flux detector, peak-picked, replacing only kicks: CCR kick F1 0.09 → ~0.60–0.63, snare/hi-hat unchanged by construction. MDB Demucs stems: F1 0.99 / 0.60 / 0.87 at one untuned threshold; Britpop precision is the weak spot (snare/bass low end).

Fixing this inside DrumScript would mean patching a third-party package; the issue allows "add a kick-specific detector". Neural engines are blocked by licence (docs/transcription-engine-evaluation.md).

## Design

- `KickDetector` protocol + `LowBandKickDetector` (our own DSP, librosa, backend process) returning kick onset times from the drum stem.
- `KickAugmentedTranscriber(base: DrumTranscriber, detector: KickDetector)` behind the existing `DrumTranscriber` boundary: returns **all base events unchanged** plus detector kicks that are not within 50 ms of a base kick. Added events: `provenance="kick_detector"`, `confidence=None` (no calibrated signal; flux strength is not a confidence). DrumScript's raw output therefore stays fully present in `raw_transcription.json`, separable by provenance.
- Union-with-dedupe vs replace is decided by measurement in Task 5; the default is union because it preserves raw output. If replace measures materially better, stop and report before switching.

## Fixtures

- **MDB Drums** (github.com/CarlSouthall/MDBDrums, CC BY-NC-SA 4.0): 23 MedleyDB songs, full mix + drum-only + per-hit class annotations (`<time>\t<KD|SD|HH|TT|CY|OT>`). Fetched locally, never committed (same policy as tempo fixtures). Production path: full mix → `DemucsStemSeparator` → transcriber. The drum-only track is scored too, as a second condition.
- Class groups scored: kick=KD, snare=SD, hihat=HH (hihat_closed+hihat_open), toms=TT (3 toms), cymbals=CY (crash+ride). OT ignored.
- Tuning split to avoid overfitting: songs sorted by name, even indices = tune, odd = held-out. Parameters are chosen on tune only; held-out numbers are what the docs claim.
- CCR vs product owner's MIDI: secondary check with the documented release-report method (fan MIDI, not ground truth).
- IDMT-SMT-Drums: not used (CC BY-NC-ND, drum-only loops; MDB covers real songs through our Demucs path). Note in the evaluation doc.

## Tasks

### 1. Reusable scoring in `app/benchmark.py`
- Extract the per-instrument P/R/F1 computation from `evaluate_transcriber` into `score_hits(predicted: Sequence[HasTime], expected: Sequence[HasTime], tolerance) -> MatchCounts` (tp/fp/fn + precision/recall/f1). Rename `_match_instrument` → `match_hits` (public, used by the new module). `evaluate_transcriber` keeps its behaviour.
- Tests (`tests/test_benchmark.py`): existing ones pass unchanged; `test_score_hits_counts_precision_recall_f1` (2 of 3 expected matched, 1 extra → P=2/3, R=2/3); `test_score_hits_empty_inputs_are_zero_not_error`.

### 2. Real-audio benchmark `app/drum_benchmark.py`
```
uv run python -m app.drum_benchmark fetch <dir>                      # download MDB + Demucs, once
uv run python -m app.drum_benchmark run <dir> [--engine drumscript|augmented] [--condition demucs|drum_only]
```
- `MDB_SONGS: tuple[str, ...]` (23 names), `split(songs) -> (tune, held_out)`.
- `parse_annotations(text) -> list[LabelledHit(time, group)]` (skip blank/OT).
- `INSTRUMENT_GROUPS: dict[str, frozenset[DrumInstrument]]`.
- `evaluate_song(events, hits, tolerance) -> dict[group, MatchCounts]`, `pool(results) -> dict[group, MatchCounts]` (sum tp/fp/fn, recompute P/R/F1).
- `fetch_songs(root, download: Callable[[str, Path], None], separator)`: skips songs already present; writes `<dir>/<song>/{mix.wav,drum_only.wav,annotations.txt,drums.wav}`.
- `run_benchmark(root, transcriber, condition, out) -> int`: per-song and pooled tables for tune / held-out / all; returns 0 (a measurement tool, not a gate).
- Tests (`tests/test_drum_benchmark.py`, fakes only, no network/Demucs): annotation parsing incl. OT/blank; group mapping puts hihat_open+closed in `hihat`; `evaluate_song` per group; `pool` sums counts (not averages F1); split is deterministic and disjoint and covers all; `fetch_songs` skips existing and calls separator once per missing song; `run_benchmark` prints pooled kick row for a fake transcriber.
- `main` is `# pragma: no cover` (wires real engines), as in `tempo_benchmark`.

### 3. `LowBandKickDetector` in `app/kick_detection.py`
- `class KickDetector(Protocol): def detect(self, audio_path: Path) -> list[float]: ...`
- `LowBandKickDetector(low_hz=30, high_hz=150, delta=..., min_interval_s=0.08)`: mono 44.1 kHz load, STFT (n_fft 2048, hop 256), band sum → `log1p(100·x)` → positive first difference → normalised by its max → `librosa.util.peak_pick` → frame times. Returns sorted list; silent/empty audio → `[]`.
- Tests (`tests/test_kick_detection.py`, synthetic WAVs in tmp_path): `test_detects_low_sine_bursts_at_their_onsets` (60 Hz decaying bursts at known times, each found within 20 ms, no extras); `test_ignores_high_frequency_noise_bursts` (hat-like 8 kHz+ noise → none); `test_detects_kicks_under_simultaneous_hats`; `test_is_gain_independent` (same audio ×0.1 → same times); `test_silence_returns_empty`; `test_respects_min_interval`.

### 4. `KickAugmentedTranscriber` in `app/kick_augmented_transcriber.py`
- Tests with a fake base transcriber and fake detector: `test_keeps_all_base_events_unchanged` (same ids/times/provenance); `test_adds_detector_kicks_with_provenance_and_no_confidence`; `test_skips_detector_kick_within_tolerance_of_base_kick`; `test_keeps_detector_kick_near_non_kick_base_event` (a snare at the same time does not suppress it); result sorted by time; base `TranscriptionError` propagates.

### 5. Tune and measure (no committed code beyond constants)
- `fetch` MDB (23 songs through Demucs). Baseline: `run --engine drumscript` for both conditions.
- Grid on **tune** split, demucs condition: `delta ∈ {0.2,0.3,0.4,0.5}`, `high_hz ∈ {120,150}`, `min_interval_s ∈ {0.06,0.08,0.1}`, plus one precision guard if Britpop-type false kicks dominate (low-band flux must exceed mid-band 150–500 Hz flux at the peak). Objective: pooled kick F1; tie-break precision. Freeze constants in `LowBandKickDetector` defaults with a comment pointing to the evaluation doc.
- Measure held-out + drum_only + CCR MIDI check; confirm snare/hihat/toms/cymbals pooled F1 identical to baseline (they must be, by construction).
- Stop and report if held-out kick recall does not materially improve or precision collapses.

### 6. Wire in, version, docs
- `app/worker/factory.py`: `transcriber=KickAugmentedTranscriber(DrumScriptTranscriber(), LowBandKickDetector())`; test in `tests/test_worker_factory.py` asserts the type/composition.
- `PIPELINE_VERSION = "3"` (transcriber changed → stale stage cache must not be reused).
- `docs/kick-detection-evaluation.md`: root cause, method, split, before/after tables (held-out headline), CCR check, limitations (bass bleed, double-kick, precision on dense low-end songs).
- `docs/ARCHITECTURE_V1.md` Transcription section: one paragraph on the composition and provenance.
- `docs/RELEASE_REPORT_V1.md` item 3: "fixed in V1-037, see …".
- `TECHNICAL_DEBT.md`: "Benchmark corpus's synthetic audio" → partially resolved (real-audio benchmark exists for kick/snare/hihat/toms/cymbals via MDB); "Generated notation doesn't look right (classifier accuracy)" → note kick part addressed, snare (F1 ~0.56 on CCR) remains; add any new debt found. Update the index.
- `backend/tests/fixtures/README.md`: how to fetch/run the MDB benchmark and the licence note.

### 7. Verify
- Full backend suite + ruff/mypy as configured; frontend suite untouched but run before PR.
- Container check on a separate project name (`docker compose -p drumscore-v1037`, `deploy/.env` ports 18000/13000): process CCR, confirm kick count in `raw_transcription.json` is in the reference's range and kicks appear in the rendered score (Playwright screenshot for the PR).
- PR "Fixes #114, part of #86" with root cause, before/after tables, scope-outs (snare quality, IDMT).
