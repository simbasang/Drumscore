# V1-036 Tempo octave-error correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The beat map (and the tempo shown) lands on the musical beat for real songs: no 2×/0.5×/1.5× errors and no drift, measured on labelled real-song fixtures.

**Architecture:** Replace `LibrosaTempoEstimator` + `LibrosaBeatDetector` (a constant grid from one BPM) with a `BeatThisBeatDetector` (CPJKU Beat This!, MIT code+weights) behind the existing `BeatDetector` protocol. It runs on the full mix, rebuilt as drums + accompaniment stems. `tempo_bpm` is derived from the detected beats, so there is only one tempo source. Detected downbeats set the measure phase; the meter stays 4/4 (frontend and quantizer hardcode it).

**Tech Stack:** Python 3.13, beat-this 1.1.0 (latest on PyPI, checked 2026-09-26), torch (already present), soundfile, pytest.

**Spec:** GitHub issue #113; evidence below.

## Root cause (reproduced 2026-09-26 on the release-pass stems)

1. `LibrosaTempoEstimator._score_candidates` chooses between 0.5/⅔/1/1.5/2× of librosa's tempo using the mean phase error of onsets against a grid anchored at t=0. On real songs, tiny tempo errors accumulate over minutes, so onset phases are uniformly spread and every candidate scores ≈0.25 (the value for random onsets). The choice is noise and overrides librosa's correct 114.8: CCR → 229.7, Rick → 57.4, Hotel California → 295.3. The existing tests only use perfect synthetic grids from t=0, the one case where it works.
2. `LibrosaBeatDetector` lays one constant-tempo grid over the whole song. Even at the right octave it drifts 1.5 s (CCR) and 1.9 s (Rick) from librosa's own tracked beats by the end of the song, about 3 beats.

## Evidence for the engine choice (8 songs, ±4%)

| Song (YouTube ID) | Ref | Current | librosa tracker | Beat This! drums | Beat This! mix |
|---|---|---|---|---|---|
| CCR `bO28lB1uwp4` | 116 | 229.7 ✘ | 117.5 | 115.4 | 115.4 |
| Rick Astley `dQw4w9WgXcQ` | 113 | 57.4 ✘ | 112.3 | 115.4 | 115.4 |
| Hotel California `dLl4PZtxia8` | 75 | 295.3 ✘ | 73.8 | 73.2 | 75.0 |
| Blitzkrieg Bop `skdE0KAFCEA` | 177 | 175.2 | 89.1 ✘ | 176.5 | 176.5 |
| Everybody Wants… `aGCdLKXNF3w` | 112 | 224.7 ✘ | 112.3 | 166.7 ✘ | 111.1 |
| We Are the Champions `04854XqcfCY` (6/8, dotted quarter) | 64 | 146.3 ✘ | 63.0 | 63.8 | 65.2 |
| Back in Black `pAgnJDJN4VA` | 93 | 187.9 ✘ | 95.7 | 93.7 | 93.8 |
| Billie Jean `Zi_XLOBDo_Y` | 117 | 234.9 ✘ | 117.5 | 115.4 | 115.4 |

A backbeat-alternation heuristic prototype scored 3/5 and was dropped. On the mix, Beat This! downbeats give 4 beats/bar on the 4/4 songs and 2 on the 6/8 song. References are published values (getsongbpm/songbpm/tunebat/Hooktheory; CCR also from the product owner's MIDI = 115). The product owner chose Beat This! on the mix.

Note: Beat This! beats sit on a 20 ms frame grid, so a median of single inter-beat intervals is quantized (115.4 = 26 frames). Derive tempo from the median of 4-beat spans ÷ 4.

## Global Constraints

- Source time is authoritative; beats are source-time points, never re-derived from a BPM.
- No fabricated confidence: `BeatPoint.confidence = None` (Beat This! outputs no calibrated confidence).
- Third-party output never becomes a contract: Beat This! stays inside `app/beat_this_beat_detector.py`.
- API/analysis contract (`tempo_bpm`, `beats[]`) is unchanged; bump `PIPELINE_VERSION` to `"2"`.
- Tests: `uv run pytest -q --tb=short <path>` while iterating; full suite + ruff before commits.

## Review Focus

1. Long drumless intro/outro: events before the first beat still get measure ≥ 1 (existing shift in `map_tempo`). Test in Task 3.
2. Stems of different lengths: the mix pads the shorter one; a sample-rate mismatch raises a clear error. Tests in Task 2.
3. Silent or near-silent audio: < 2 beats → the existing `InsufficientBeatsError`, not a crash. Test in Task 1 (pure function with 0 or 1 beats) and Task 3.
4. Container runs offline: the checkpoint must be baked into the image, not downloaded on the first job. Verified in Task 4.
5. The temp mix file is removed even when beat detection fails. Test in Task 3.

---

### Task 1: `BeatThisBeatDetector` (numbering + tempo from beats)

**Files:**
- Create: `backend/app/beat_this_beat_detector.py`
- Create: `backend/tests/test_beat_this_beat_detector.py`
- Modify: `backend/pyproject.toml`, `uv.lock` (`uv add beat-this==1.1.0`, i.e. `>=1.1.0`)

**Interfaces (produces):**
- `beat_points_from_tracker(beat_times: Sequence[float], downbeat_times: Sequence[float], beats_per_measure: int = 4) -> list[BeatPoint]`
- `tempo_from_beats(beats: Sequence[BeatPoint]) -> float`: median of `(t[i+4] - t[i]) / 4` spans (fall back to single intervals when < 5 beats); raises `ValueError` with < 2 beats
- `class BeatThisBeatDetector` with `__init__(self, tracker: Callable[[Path], tuple[np.ndarray, np.ndarray]] | None = None)` and `detect(audio_path: Path) -> list[BeatPoint]`. The default tracker lazily builds `File2Beats(checkpoint_path="final0", device="cpu", dbn=False)` once per instance. Any tracker exception → `BeatDetectionError`.

**Numbering rule:** phase = most common `(index of the beat nearest each downbeat) % beats_per_measure` (ties → smallest; no downbeats → 0). For beat i: `offset = 1 if phase > 0 else 0`, `measure = (i - phase) // bpm + 1 + offset`, `beat = (i - phase) % bpm + 1`, `is_downbeat = beat == 1`. Pickup beats land in measure 1 (e.g. phase 2 → beats 3, 4), then measure 2 starts on the first downbeat.

**Tests (TDD, pure functions first):**
- `test_numbers_beats_in_fours_from_the_first_beat_when_it_is_a_downbeat`: 8 beats, downbeats at beats 0 and 4 → measures 1,1,1,1,2,2,2,2; beat numbers 1..4.
- `test_puts_pickup_beats_before_the_first_downbeat_in_measure_one`: downbeats at indices 2 and 6 → first two beats are (1,3),(1,4), index 2 → (2,1) with `is_downbeat`.
- `test_follows_the_majority_downbeat_phase_when_one_downbeat_is_off`: downbeats at 0, 4, 9, 12 → phase 0.
- `test_starts_at_beat_one_when_no_downbeats_are_detected`.
- `test_keeps_tracker_beat_times_unchanged_as_source_times`: variable intervals are preserved exactly (no grid).
- `test_leaves_confidence_empty`.
- `test_returns_no_beats_for_an_empty_tracker_result`.
- `test_tempo_from_beats_is_not_quantized_to_single_frame_intervals`: beats on a 20 ms-rounded 113 BPM grid → within 0.5 BPM of 113.
- `test_tempo_from_beats_ignores_a_single_missed_beat`.
- `test_tempo_from_beats_rejects_fewer_than_two_beats`.
- `test_detect_passes_the_audio_path_to_the_tracker` (fake tracker).
- `test_detect_wraps_tracker_failures_in_beat_detection_error`.
- `test_detect_finds_a_click_track_tempo_with_the_real_model`: synthetic 8 s, 100 BPM accented click (accent every 4th) → tempo within 4% of 100. This uses the real checkpoint (downloaded to the torch cache on the first run).

- [ ] Write failing tests → run → implement → pass → ruff → commit `feat(timing): Beat This! beat detector with downbeat-phased numbering`

### Task 2: Rebuild the mix from stems

**Files:**
- Create: `backend/app/audio_mix.py`, `backend/tests/test_audio_mix.py`

**Interfaces (produces):** `mix_stems(drums_path: Path, accompaniment_path: Path, destination: Path) -> Path` writes float32 WAV `drums + accompaniment` (the shorter one zero-padded; mono/stereo mismatch → broadcast to the wider one), returns `destination`. Different sample rates → `ValueError("... sample rates differ ...")`.

**Tests:** `test_mix_is_the_sample_wise_sum_of_both_stems`, `test_pads_the_shorter_stem_with_silence`, `test_rejects_stems_with_different_sample_rates`, `test_mixes_a_mono_stem_into_a_stereo_stem`.

- [ ] TDD cycle → commit `feat(pipeline): rebuild the full mix from drum and accompaniment stems`

### Task 3: Wire into `map_tempo`, runner and worker; remove the old engines

**Files:**
- Modify: `backend/app/pipeline/tempo_mapping.py`: `map_tempo(analysis_audio_path: Path, events, beat_detector) -> TempoMappingResult`; `tempo_bpm = tempo_from_beats(beats)` after the `< 2` beats check; `TempoMap.constant(tempo_bpm)` stays (docstring: the median tempo of the detected beats).
- Modify: `backend/app/pipeline/runner.py`: `JobEngines` loses `tempo_estimator`; `_map_tempo_and_complete` mixes the drums + accompaniment artifacts into a `tempfile.TemporaryDirectory()` and passes the mix.
- Modify: `backend/app/worker/factory.py` → `BeatThisBeatDetector()`.
- Modify: `backend/app/pipeline/version.py` → `"2"`.
- Delete: `app/librosa_tempo_estimator.py`, `app/tempo_estimation.py`, `app/librosa_beat_detector.py` and their tests; remove the fake tempo estimator from `tests/fakes.py`; update `tests/test_tempo_mapping.py`, `tests/test_runner.py`, `tests/test_worker_factory.py` (and any other user found by grep).

**Tests:**
- `test_map_tempo_derives_tempo_bpm_from_the_detected_beats` (fake beats at 0.5 s → 120).
- Keep the shift/quantize/no-events tests with the new signature.
- `test_map_tempo_requires_two_beats` still raises `InsufficientBeatsError`.
- Runner: `test_map_tempo_stage_analyses_the_mix_of_both_stems` (a recording fake detector reads the file it gets: equals drums + accompaniment); `test_map_tempo_stage_removes_the_temporary_mix_when_detection_fails`.

- [ ] TDD cycle → full backend suite → commit `fix(timing): track beats with Beat This! on the full mix instead of a constant grid (#113)`

### Task 4: Container: bake the checkpoint

**Files:** Modify `backend/Dockerfile`: set `TORCH_HOME=/opt/torch` in the build and runtime stages, add `RUN .venv/bin/python -c "from beat_this.inference import File2Beats; File2Beats(checkpoint_path='final0', device='cpu')"` next to the Demucs pre-fetch, and `COPY --from=build /opt/torch /opt/torch`. Update `docs/DEPLOYMENT.md` (image contents/size) if it lists baked models.

- [ ] Build the image, then run a job with the network disabled for the worker (or check that no `cloud.cp.jku.at` request occurs in the logs) → commit `build: bake the Beat This! checkpoint into the backend image`

### Task 5: Real-song tempo benchmark (fixtures + metric)

**Files:**
- Create: `backend/app/tempo_benchmark.py`, `backend/tests/test_tempo_benchmark.py`, `backend/tests/fixtures/real_tempo_songs.py`

**Interfaces:**
- `TempoFixture(video_id: str, title: str, reference_bpm: float, meter: str, sources: str)`; `REAL_TEMPO_SONGS: tuple[TempoFixture, ...]` = the 8 songs in the table above.
- `classify_tempo(detected: float, reference: float, tolerance: float = 0.04) -> str` returns one of `"correct"`, `"double"`, `"half"`, `"three_halves"`, `"two_thirds"`, `"other"`.
- `evaluate(fixtures, detect_bpm: Callable[[TempoFixture], float | None]) -> list[TempoResult]` (None → `"missing"`); `TempoResult(fixture, detected_bpm, verdict)`.
- CLI: `python -m app.tempo_benchmark fetch <dir>` (yt-dlp + Demucs into `<dir>/<id>/{drums,accompaniment}.wav`, skipping songs that already exist) and `python -m app.tempo_benchmark run <dir>` (mix → `BeatThisBeatDetector` → `tempo_from_beats`; prints a table and exits 1 if any verdict isn't `correct`). Audio is never committed.

**Tests:** each `classify_tempo` verdict incl. the ±4% boundary; `evaluate` with a fake detector incl. missing stems; the fixture table has 8 unique IDs with positive references.

- [ ] TDD cycle → run `fetch` + `run` on the 8 songs → expect 8/8 `correct` → commit `test(timing): real-song tempo fixtures and octave-correctness metric`

### Task 6: Verify end to end, and docs

- [ ] Rebuild the stack (`deploy/.env`, ports 18000/13000), process CCR, and check in the browser (Playwright): 8ths beamed (not unbeamed 16ths), about 4 s measures at ~116 BPM, and the metronome/count-in click at the beat rate (click period from `beats`). Screenshot for the PR.
- [ ] Beat drift check: tracked beats vs. the old constant grid on CCR/Rick (show the end-of-song offset is gone).
- [ ] Docs: `docs/tempo-evaluation.md` (method, fixture table, results before/after, limitations); `TECHNICAL_DEBT.md`: move "Tempo estimation disagrees…" to `docs/technical-debt-resolved.md` and add "Meter is hardcoded 4/4 (6/8, 12/8 are notated in a 4/4 16th grid; detected downbeats only set phase)" and "TempoMap is still a single median tempo" to the index; `docs/ARCHITECTURE_V1.md` Timing section (beat engine, mix input); `docs/RELEASE_REPORT_V1.md` tempo row → points to #113's fix (the gate stays open for #114).
- [ ] Full backend + frontend suites, ruff/lint/tsc → commit → push → PR "Fixes #113" (not #86).
