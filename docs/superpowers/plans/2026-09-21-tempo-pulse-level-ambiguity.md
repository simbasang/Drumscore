# Tempo Pulse-Level Ambiguity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `LibrosaTempoEstimator`'s candidate correction beyond octave (half/double) errors to also cover the documented 1.5x simple-vs-compound pulse-level ambiguity (`TECHNICAL_DEBT.md`, "Tempo estimation disagrees with DrumScript's own estimate": 123 vs 184.6 BPM, `123 × 1.5 ≈ 184.6`), and expose the full candidate evidence for inspection instead of only a bare winning float.

**Root cause (already diagnosed in `TECHNICAL_DEBT.md`, confirmed by reading `_correct_octave_error` directly):** the existing correction only ever considers three candidates — `tempo`, `tempo × 2`, `tempo / 2` — because it was built specifically to fix octave errors. A 1.5x pulse-level ambiguity (mistaking a compound-meter pulse for a simple one, or vice versa) is architecturally the same kind of problem — the beat tracker locked onto a plausible but wrong periodicity — just a different ratio. The fix is not a new algorithm, it's a bigger, still-general candidate set scored by the same phase-fit heuristic that already works.

**Architecture:** Extend the existing candidate-ratio list in `librosa_tempo_estimator.py` from `{0.5, 1, 2}` to `{0.5, 2/3, 1, 1.5, 2}` — covering octave-down, pulse-down (compound→simple), original, pulse-up (simple→compound), octave-up — still scored by the same onset-phase-fit function already in place, still bounded by `_MIN_BPM`/`_MAX_BPM`, still ordered slowest-first for the same stable tie-break the existing code comment explains. Add `TempoCandidate`/`TempoEstimate` dataclasses to `app/tempo_estimation.py` (alongside the existing `TempoEstimator` protocol — the natural shared-contracts home, matching how `BeatPoint`/`TempoMap` live in `app/timing.py`). `LibrosaTempoEstimator.estimate()` keeps its exact existing signature and behavior (still returns a bare `float`) so `job_processor.py` and every existing test/consumer is untouched; a new `estimate_with_evidence()` method returns the full `TempoEstimate` with every candidate considered — the "candidates/evidence are inspectable" contract, added beside the old one rather than replacing it (this epic's established migration pattern from #39/#40).

**Explicitly out of scope:** wiring DrumScript's own tempo estimate through as a second evidence source (`TECHNICAL_DEBT.md` names this as *one* possible fix; this plan achieves the acceptance criteria without it, since cross-validating candidate ratios against the onset evidence already on hand is sufficient and doesn't require touching the DrumScript subprocess boundary). No `job_processor.py`/`Job` wiring of `estimate_with_evidence()` — that's for whichever later issue wants to surface tempo evidence in diagnostics or the API, not this one.

**Tech Stack:** Python 3.13, numpy, librosa, pytest — existing backend dependencies.

**Spec:** GitHub issue #41 (V1-008), part of EPIC 2 (#29). Builds on the existing `_correct_octave_error` (renamed `_correct_pulse_error` to reflect its broadened scope) in `backend/app/librosa_tempo_estimator.py`.

## Global Constraints

- No song-specific/hardcoded values (no literal `123`/`184.6` anywhere) — the fix must be a general ratio-based candidate set, tested against synthetic audio at arbitrary tempos, matching this issue's explicit "no hardcoded song-specific rule" criterion.
- `estimate()`'s existing signature/behavior must not change — every existing caller (`job_processor.py`, existing tests) stays untouched.
- Keep the phase-fit scoring function itself unchanged in logic — only the candidate *set* grows. Don't rewrite what's already proven to work.
- Follow the existing tie-break comment's reasoning (slowest-first ordering for stable `min()` tie-breaking) when extending the candidate list.

---

### Task 1: Extend the candidate set to cover the 1.5x pulse-level ambiguity

**Files:**
- Modify: `backend/app/librosa_tempo_estimator.py`
- Test: `backend/tests/test_librosa_tempo_estimator.py`

**Interfaces:**
- `LibrosaTempoEstimator.estimate(audio_path: Path) -> float` - signature unchanged, now scores 5 candidates instead of 3.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_librosa_tempo_estimator.py`:

```python
def test_estimate_corrects_a_1_5x_error_when_beat_tracker_reports_the_compound_pulse(tmp_path):
    # A classic simple-vs-compound pulse-level ambiguity: the beat tracker
    # locks onto 2/3 of the true tempo (TECHNICAL_DEBT.md's 123-vs-184.6
    # case is this same ratio: 123 * 1.5 ~= 184.6).
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=180.0)
    true_period = 60.0 / 180.0
    onset_times = np.arange(0, 8.0, true_period)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(120.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=onset_times),
    ):
        bpm = LibrosaTempoEstimator().estimate(audio_path)

    assert bpm == pytest.approx(180.0, abs=1.0)


def test_estimate_corrects_a_1_5x_error_when_beat_tracker_reports_the_simple_pulse(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)
    true_period = 60.0 / 120.0
    onset_times = np.arange(0, 8.0, true_period)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(180.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=onset_times),
    ):
        bpm = LibrosaTempoEstimator().estimate(audio_path)

    assert bpm == pytest.approx(120.0, abs=1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_librosa_tempo_estimator.py -v -k "1_5x"`
Expected: FAIL - the current 3-candidate set (`{60, 120, 240}` from a raw 120.0 estimate, or `{90, 180, 360}` from a raw 180.0 estimate) never contains the true tempo when the error is 1.5x, not an octave, so the phase-fit winner is wrong.

- [ ] **Step 3: Extend the candidate set**

In `backend/app/librosa_tempo_estimator.py`, replace `_correct_octave_error`:

```python
def _correct_octave_error(tempo: float, onset_times: np.ndarray) -> float:
```

with (renamed to reflect the broadened scope, same external call site in `estimate()`):

```python
# Ratios covering both octave errors (0.5x/2x) and simple-vs-compound
# pulse-level errors (2/3x/1.5x, e.g. TECHNICAL_DEBT.md's 123-vs-184.6
# case: 123 * 1.5 ~= 184.6) - the same class of mistake (the beat
# tracker locked onto a plausible but wrong periodicity), scored by the
# same phase-fit heuristic. Ascending order matters for the stable
# tie-break explained below.
_CANDIDATE_RATIOS: tuple[float, ...] = (0.5, 2.0 / 3.0, 1.0, 1.5, 2.0)


def _correct_pulse_error(tempo: float, onset_times: np.ndarray) -> float:
    """Beat trackers commonly report a plausible but wrong multiple of the
    true tempo - not just an octave (half/double) but also a simple-vs-
    compound pulse-level mistake (2/3x or 1.5x). Prefer whichever candidate
    best fits the actual onset positions, since the raw beat-tracker
    estimate alone can't distinguish between them."""
    if onset_times.size == 0:
        return tempo

    # Slowest first: onsets landing exactly on a coarse grid also land
    # exactly on every finer multiple of it, so ties are common. Ordering
    # candidates slowest-to-fastest makes min()'s stable tie-break prefer
    # the slower tempo whenever two candidates fit equally well.
    candidates = [
        tempo * ratio for ratio in _CANDIDATE_RATIOS if _MIN_BPM <= tempo * ratio <= _MAX_BPM
    ]

    def phase_error(bpm: float) -> float:
        beat_period = 60.0 / bpm
        phase = (onset_times % beat_period) / beat_period
        distance_to_nearest_beat = np.minimum(phase, 1 - phase)
        return float(np.mean(distance_to_nearest_beat))

    return min(candidates, key=phase_error)
```

Update the two call sites inside `estimate()`/wherever `_correct_octave_error` was called to use the new name `_correct_pulse_error`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_librosa_tempo_estimator.py -v`
Expected: PASS (all tests in the file, including every pre-existing octave-error test - no regressions, since `{0.5, 1, 2}` is a subset of the new `{0.5, 2/3, 1, 1.5, 2}` ratio set).

- [ ] **Step 5: Commit**

```bash
git add backend/app/librosa_tempo_estimator.py backend/tests/test_librosa_tempo_estimator.py
git commit -m "fix: extend tempo candidate correction to cover 1.5x pulse-level ambiguity"
```

---

### Task 2: Expose inspectable candidate evidence

**Files:**
- Modify: `backend/app/tempo_estimation.py`
- Modify: `backend/app/librosa_tempo_estimator.py`
- Test: `backend/tests/test_librosa_tempo_estimator.py`

**Interfaces:**
- Produces: `TempoCandidate(bpm: float, phase_error: float)`, `TempoEstimate(bpm: float, candidates: tuple[TempoCandidate, ...])` in `app/tempo_estimation.py`. `LibrosaTempoEstimator.estimate_with_evidence(audio_path: Path) -> TempoEstimate` - new method, `estimate()` stays exactly as it is (now implemented as `self.estimate_with_evidence(audio_path).bpm` internally, but callers see no change).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_librosa_tempo_estimator.py`:

```python
from app.tempo_estimation import TempoCandidate, TempoEstimate


def test_estimate_with_evidence_exposes_every_candidate_considered(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)
    true_period = 60.0 / 120.0
    onset_times = np.arange(0, 8.0, true_period)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(80.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=onset_times),
    ):
        result = LibrosaTempoEstimator().estimate_with_evidence(audio_path)

    assert isinstance(result, TempoEstimate)
    assert result.bpm == pytest.approx(120.0, abs=1.0)
    # 80 * {0.5, 2/3, 1, 1.5, 2} = {40, 53.3, 80, 120, 160} - all within
    # [_MIN_BPM, _MAX_BPM], so all 5 candidates should be present.
    assert len(result.candidates) == 5
    assert all(isinstance(c, TempoCandidate) for c in result.candidates)


def test_estimate_with_evidence_bpm_matches_the_lowest_phase_error_candidate(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)
    true_period = 60.0 / 120.0
    onset_times = np.arange(0, 8.0, true_period)

    with (
        patch("app.librosa_tempo_estimator.librosa.beat.beat_track", return_value=(80.0, None)),
        patch("app.librosa_tempo_estimator.librosa.onset.onset_detect", return_value=onset_times),
    ):
        result = LibrosaTempoEstimator().estimate_with_evidence(audio_path)

    winner = min(result.candidates, key=lambda c: c.phase_error)
    assert winner.bpm == pytest.approx(result.bpm, abs=1e-6)


def test_estimate_returns_the_same_bpm_as_estimate_with_evidence(tmp_path):
    audio_path = tmp_path / "clicks.wav"
    _write_click_track(audio_path, bpm=120.0)

    bpm = LibrosaTempoEstimator().estimate(audio_path)
    result = LibrosaTempoEstimator().estimate_with_evidence(audio_path)

    assert bpm == result.bpm
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_librosa_tempo_estimator.py -v -k "with_evidence"`
Expected: FAIL - `TempoCandidate`/`TempoEstimate` don't exist yet; `estimate_with_evidence` doesn't exist yet.

- [ ] **Step 3: Implement**

In `backend/app/tempo_estimation.py`, add:

```python
import dataclasses
```

```python
@dataclasses.dataclass(frozen=True)
class TempoCandidate:
    bpm: float
    phase_error: float


@dataclasses.dataclass(frozen=True)
class TempoEstimate:
    bpm: float
    candidates: tuple[TempoCandidate, ...]
```

In `backend/app/librosa_tempo_estimator.py`, change `_correct_pulse_error` to return the full candidate list instead of just the winner, and add `estimate_with_evidence`:

```python
def _score_candidates(tempo: float, onset_times: np.ndarray) -> list[TempoCandidate]:
    """All plausible tempo candidates (octave and pulse-level ratios of the
    raw estimate), each scored by how well it fits the actual onset
    positions. Ordered slowest-first for a stable tie-break when two
    candidates fit equally well (see _CANDIDATE_RATIOS's comment)."""
    bpms = [
        tempo * ratio for ratio in _CANDIDATE_RATIOS if _MIN_BPM <= tempo * ratio <= _MAX_BPM
    ]

    def phase_error(bpm: float) -> float:
        if onset_times.size == 0:
            return 0.0
        beat_period = 60.0 / bpm
        phase = (onset_times % beat_period) / beat_period
        distance_to_nearest_beat = np.minimum(phase, 1 - phase)
        return float(np.mean(distance_to_nearest_beat))

    return [TempoCandidate(bpm=bpm, phase_error=phase_error(bpm)) for bpm in bpms]
```

Replace the `estimate` method body and add `estimate_with_evidence`:

```python
    def estimate(self, audio_path: Path) -> float:
        return self.estimate_with_evidence(audio_path).bpm

    def estimate_with_evidence(self, audio_path: Path) -> TempoEstimate:
        try:
            y, sr = librosa.load(str(audio_path), sr=None, mono=True)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo = float(np.asarray(tempo).reshape(-1)[0])
            onset_times = librosa.onset.onset_detect(y=y, sr=sr, units="time")
            candidates = _score_candidates(tempo, np.asarray(onset_times))
        except Exception as error:
            raise TempoEstimationError(f"Failed to estimate tempo: {error}") from error

        if not candidates:
            return TempoEstimate(bpm=tempo, candidates=())

        winner = min(candidates, key=lambda c: c.phase_error)
        return TempoEstimate(bpm=winner.bpm, candidates=tuple(candidates))
```

Remove the now-unused standalone `_correct_pulse_error` function (its logic is now inside `_score_candidates` + the `min()` call in `estimate_with_evidence`) and add the import:

```python
from app.tempo_estimation import TempoCandidate, TempoEstimate, TempoEstimationError
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_librosa_tempo_estimator.py -v`
Expected: PASS (all tests, including Task 1's and every pre-existing test - no regressions). Note: the pre-existing `test_estimate_leaves_tempo_unchanged_when_no_onsets_are_detected` test must still pass - `_score_candidates` returns `phase_error=0.0` for every candidate when there are no onsets, so `min()` picks the first (slowest) candidate by the stable tie-break, which for a tempo already in a sane range and no onset evidence should still equal the original raw tempo's closest in-range candidate. If this test fails, adjust `estimate_with_evidence`'s no-onset branch to return the *original* raw tempo unchanged (matching current documented behavior) rather than the first candidate - re-run to confirm before moving on.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tempo_estimation.py backend/app/librosa_tempo_estimator.py backend/tests/test_librosa_tempo_estimator.py
git commit -m "feat: expose inspectable tempo-candidate evidence via estimate_with_evidence"
```

---

## Self-Review Notes

- **Spec coverage:** "123-vs-184.6-style fixture/case is handled by documented logic" -> Task 1's two 1.5x tests, general ratio-based (no literal 123/184.6 anywhere), documented in the code comment referencing the debt entry. "candidates/evidence are inspectable" -> Task 2's `TempoEstimate`/`TempoCandidate`. "no hardcoded song-specific rule" -> `_CANDIDATE_RATIOS` is a fixed set of *ratios*, applied to whatever the raw estimate is, never a literal BPM value. "tests cover half/double and 1.5x ambiguity" -> pre-existing octave tests (Task 1 confirms no regression) plus the two new 1.5x tests.
- **Backward compatibility verified, not assumed:** Task 1's step 4 explicitly re-runs every pre-existing test, and Task 2 keeps `estimate()`'s signature/behavior identical (proven by `test_estimate_returns_the_same_bpm_as_estimate_with_evidence`) - `job_processor.py` needs zero changes.
- **Edge case flagged for verification, not silently assumed:** Task 2 Step 4 explicitly calls out the no-onset case needs re-checking against the pre-existing test rather than assuming the refactor preserves it correctly.
