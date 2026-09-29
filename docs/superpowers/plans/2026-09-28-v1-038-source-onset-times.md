# V1-038 — DrumScript source onset times Implementation Plan

> **For agentic workers:** executed inline (repo CLAUDE.md default). Steps use checkbox (`- [ ]`) syntax.

**Goal:** DrumScript-derived events carry DrumScript's detected onset times, not the 16th-grid times `build_score` writes over them.

**Architecture:** `drumscript.transcribe()` = load/normalise → tempo + `detect_onsets` → `classify_events` → `build_score` (quantizes `event["time_sec"]` in place, writes PDF/JSON/MIDI). The runner reproduces the first three steps itself (same calls and arguments as `transcribe(full_song=False, is_rudiment=False)`) and skips tempo and `build_score`. `build_score` only mutates `time_sec`, so instruments are unchanged. The `DrumTranscriber` boundary and the `raw_transcription`/`engine_transcription` artifacts are unchanged.

**Tech Stack:** Python 3.12 runner venv (drumscript 0.2.x), pytest.

**Spec:** GitHub issue #118.

## Global Constraints
- Source time is authoritative; quantization stays in our timing layer.
- No fabricated confidence (`confidence` stays `None`, `provenance: "drumscript"`).
- Backend tests: `uv run pytest -q --tb=short`.

## Review Focus
- Empty onset list (silent stem): runner must write `{"events": []}`, not crash — covered by a runner test.
- Stale stage cache: previously cached quantized transcriptions must not be reused — bump `PIPELINE_VERSION`.
- DrumScript prints to stdout; result still goes to the events file only (unchanged).

---

### Task 1: Runner uses onset detection + classification directly

**Files:**
- Modify: `backend/drumscript_runner/run_transcription.py`
- Modify: `backend/app/drumscript_transcriber.py` (drop the third CLI arg / `drumscript_output` dir; no side files are written any more)
- Test: `backend/tests/test_drumscript_runner_script.py`, `backend/tests/test_drumscript_transcriber.py`

**Interfaces:** runner CLI becomes `run_transcription.py <audio_path> <output_json_path>`; output JSON unchanged (`{"events": [{"time_sec", "instruments"}]}`).

Runner body: `y, sr = ds.load_audio(audio_path, sr=ds.SAMPLE_RATE)`; `y = ds.normalise_audio(y)`; `onsets = ds.detect_onsets(y, sr)`; `events = ds.classify_events(y, sr, onsets)`.

Tests (fake `drumscript` module in `sys.modules` exposing those names; no `transcribe`, no `build_score`):
- `test_main_writes_detected_onset_times_unquantized` — `classify_events` returns `time_sec` 0.2371 / 0.5012 (off any grid) plus `debug_features`; output file holds exactly those times and instruments, no extra keys.
- `test_main_classifies_the_normalised_audio_at_drumscript_sample_rate` — `load_audio` called with `sr=SAMPLE_RATE`; `detect_onsets`/`classify_events` receive the normalised array and the onsets.
- `test_main_writes_no_events_for_silent_audio` — no onsets → `{"events": []}`.
- `test_main_exits_with_usage_on_wrong_argument_count` — updated for two args.
- Adapter: `test_transcribe_invokes_runner_script_with_audio_and_output_paths` updated to the 2-arg command; remove `test_transcribe_gives_drumscript_a_scratch_output_dir_removed_afterwards` (no scratch output dir exists any more).

- [ ] Write failing tests; run; implement; run `uv run pytest -q tests/test_drumscript_runner_script.py tests/test_drumscript_transcriber.py`.
- [ ] Real-stem check: run the runner on the CCR drum stem; intervals are no longer dominated by one value (issue: 448/551 at 0.2554 s).

### Task 2: Invalidate cached transcriptions

**Files:** `backend/app/pipeline/version.py` — `PIPELINE_VERSION = "4"` (the file's own rule: bump when a transcriber changes). Existing `tests/test_runner.py` reads the constant; no new test.

### Task 3: Measurements and docs

- MDB Drums before/after: `uv run python -m app.drum_benchmark run <mdbfix> production demucs|drum_only` (before captured on main before Task 1).
- CCR before/after against the reference MIDI with `midi_compare.py` (method in `docs/RELEASE_REPORT_V1.md`), production transcriber on the V1-037 CCR drum stem.
- Docs: new section in `docs/kick-detection-evaluation.md` or a short `docs/drumscript-onset-times.md` with both tables; update `docs/ARCHITECTURE_V1.md` Transcription paragraph (runner skips `transcribe()`/`build_score`); move the #118 debt entry to `docs/technical-debt-resolved.md` and update the index; update the "Generated notation" debt entry's snare/hi-hat numbers if they change; update `docs/RELEASE_REPORT_V1.md` blocker status.
- Full backend suite + ruff, then PR. Re-running `docs/RELEASE_CHECKLIST.md` (pass 3) is the next step for #86, after merge.
