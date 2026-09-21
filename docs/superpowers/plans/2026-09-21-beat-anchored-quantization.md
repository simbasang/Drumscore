# Beat-Anchored Quantization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a beat-anchored quantizer that assigns `measure`/`beat`/`subdivision` to `DrumEvent`s using the *local* interval between real detected `BeatPoint`s (from #40) instead of a single constant-BPM grid anchored at t=0 (the existing `quantize_events` in `beat_mapping.py`) — the actual fix this whole epic exists to deliver.

**Design (worked out and hand-verified before writing this plan, not guessed):**

For each event, find the last beat point at or before its time (`beats[i]`), and the *local* beat period around it (the interval to the next point, or from the previous point if `i` is the last one — this is what makes "variable beat durations work": each event is measured against its own neighborhood, not a global average). Compute how many subdivisions past `beats[i]` the event falls (can be negative or exceed the subdivision count — both are fine, handled below), split that into a whole-beat offset and an in-range subdivision via `divmod`, then add that whole-beat offset to `beats[i]`'s own absolute beat index (`(measure-1) * beats_per_measure + (beat-1)`) to get the event's absolute beat index, and convert that back to measure/beat. This works for events before the first beat point or after the last one too, via ordinary integer arithmetic — no special-casing needed, because `beats[i]` (a real point) is always used as the anchor, never an out-of-range array index.

Hand-verified against two worked examples before writing any code:
1. **Non-zero first beat** (`beats[0]` at t=2.5, not t=0 — the exact scenario #40's detector produces): an event exactly at t=2.5 correctly quantizes to measure 1, beat 1, subdivision 0 — proving the fixed-grid-at-zero bug is actually gone, not just theoretically improved.
2. **Variable tempo** (beat interval 0.5s, then 0.6s, then 0.6s): an event inside the *second* (0.6s) interval quantizes using that interval's own duration, not the first's — and reconstructing that same position back to seconds via the inverse function returns exactly the original time (1.4s → measure 1, beat 3, subdivision 2 → 1.1 + (0 + 2/4) × 0.6 = 1.4s exactly).

An inverse function, `beat_anchored_position_to_seconds`, mirrors `musical_position_to_seconds`'s existing role (used by #35's diagnostics to compute `quantization_error_seconds`) but reconstructs time from the *local* beat anchors instead of one global BPM — this is what "quantization error can be inspected" means here: a caller quantizes, then calls this inverse function per event and diffs against the original `event.time`, exactly the pattern `build_event_diagnostics` already uses for the old constant-grid path.

**Architecture:** Two new functions in `backend/app/beat_mapping.py`, beside the existing `quantize_events`/`musical_position_to_seconds` (not replacing them): `quantize_events_with_beats(events, beats, ...)` and `beat_anchored_position_to_seconds(beats, measure, beat, subdivision, ...)`, sharing a private `_beat_period(beats, index)` helper. Both require `len(beats) >= 2` (need at least one interval to measure a duration from) and raise `ValueError` otherwise.

**Explicitly out of scope:** wiring this into `job_processor.py`/`Job` or the `/diagnostics` endpoint (that's #43, V1-010, "migrate score/playhead timeline to source timestamps" — the natural place to actually swap the live pipeline onto this path) and removing the old `quantize_events` (that's #44, V1-011, only once the new path is proven to own every consumer). This issue proves the quantization function itself, matching the same "migrate one boundary at a time" pattern already used by #39/#40/#41.

**Tech Stack:** Python 3.13, dataclasses — existing backend stack, no new dependencies.

**Spec:** GitHub issue #42 (V1-009), part of EPIC 2 (#29). Builds on `BeatPoint` (#39) and `LibrosaBeatDetector` (#40).

## Global Constraints

- `event.time` (sourceTime) must be byte-identical before and after — only `measure`/`beat`/`subdivision` change.
- `beats` must be a gapless sequence (each entry exactly one beat after the previous, matching what `LibrosaBeatDetector._build_beat_grid` actually produces) — this is what lets the implementation use `beats[i]`'s own `measure`/`beat` fields as the absolute-index reference instead of needing to search/reconstruct one.
- Do not modify `quantize_events` or `musical_position_to_seconds` - they stay as the existing, still-in-use constant-grid path until #44 removes it.
- Do not touch `job_processor.py`, `Job`, or the API layer - standalone, tested function only.

---

### Task 1: `quantize_events_with_beats` and `beat_anchored_position_to_seconds`

**Files:**
- Modify: `backend/app/beat_mapping.py`
- Test: `backend/tests/test_beat_mapping.py`

**Interfaces:**
- Consumes: `app.timing.BeatPoint` (#39).
- Produces: `quantize_events_with_beats(events: list[DrumEvent], beats: list[BeatPoint], beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE, subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT) -> list[DrumEvent]`; `beat_anchored_position_to_seconds(beats: list[BeatPoint], measure: int, beat: int, subdivision: int, beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE, subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT) -> float`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_beat_mapping.py`:

```python
from app.timing import BeatPoint


def _beat(time: float, measure: int, beat: int, is_downbeat: bool | None = None) -> BeatPoint:
    return BeatPoint(
        source_time=time,
        measure=measure,
        beat=beat,
        is_downbeat=is_downbeat if is_downbeat is not None else beat == 1,
    )


# Constant 120bpm grid starting at t=0 - lets these tests be compared
# directly against the equivalent quantize_events(..., bpm=120.0) cases.
CONSTANT_TEMPO_BEATS = [
    _beat(0.0, 1, 1),
    _beat(0.5, 1, 2),
    _beat(1.0, 1, 3),
    _beat(1.5, 1, 4),
    _beat(2.0, 2, 1),
    _beat(2.5, 2, 2),
]

# The exact scenario #40's detector produces: the first real beat is NOT
# at t=0.
OFFSET_BEATS = [
    _beat(2.5, 1, 1),
    _beat(3.0, 1, 2),
    _beat(3.5, 1, 3),
    _beat(4.0, 1, 4),
    _beat(4.5, 2, 1),
]

# A tempo change partway through: the first interval is 0.5s, the rest
# are 0.6s.
VARIABLE_TEMPO_BEATS = [
    _beat(0.0, 1, 1),
    _beat(0.5, 1, 2),
    _beat(1.1, 1, 3),
    _beat(1.7, 1, 4),
]


def test_quantize_events_with_beats_matches_the_constant_grid_case():
    events = [_event(0.13)]

    quantized = quantize_events_with_beats(events, CONSTANT_TEMPO_BEATS)

    assert quantized[0].measure == 1
    assert quantized[0].beat == 1
    assert quantized[0].subdivision == 1


def test_quantize_events_with_beats_preserves_original_time():
    events = [_event(1.23456)]

    quantized = quantize_events_with_beats(events, CONSTANT_TEMPO_BEATS)

    assert quantized[0].time == 1.23456


def test_quantize_events_with_beats_anchors_to_the_first_beats_real_time_not_zero():
    # The whole point of this epic: an event exactly at the first real
    # beat's time must quantize to beat 1, not to whatever a t=0-anchored
    # grid would have computed for that same absolute time.
    events = [_event(2.5)]

    quantized = quantize_events_with_beats(events, OFFSET_BEATS)

    assert quantized[0].measure == 1
    assert quantized[0].beat == 1
    assert quantized[0].subdivision == 0


def test_quantize_events_with_beats_uses_the_local_interval_during_a_tempo_change():
    # 1.4s falls inside the SECOND interval (1.1 -> 1.7, 0.6s long), not
    # the first (0.0 -> 0.5, 0.5s long). Using the wrong (global/first)
    # interval would produce a different subdivision.
    events = [_event(1.4)]

    quantized = quantize_events_with_beats(events, VARIABLE_TEMPO_BEATS)

    assert quantized[0].measure == 1
    assert quantized[0].beat == 3
    assert quantized[0].subdivision == 2


def test_quantize_events_with_beats_extrapolates_before_the_first_beat_point():
    # 2.25 is half a beat (0.25s, given the first 0.5s interval) before
    # the first detected beat. No special-casing - the same offset
    # arithmetic that works for in-range events also works here.
    events = [_event(2.25)]

    quantized = quantize_events_with_beats(events, OFFSET_BEATS)

    assert quantized[0].measure == 0
    assert quantized[0].beat == 4
    assert quantized[0].subdivision == 2


def test_quantize_events_with_beats_snaps_off_grid_human_timing_to_the_nearest_subdivision():
    # 0.14 is close to but not exactly on subdivision 1 (0.125s into the
    # first beat) - simulates humanized/slightly-off timing.
    events = [_event(0.14)]

    quantized = quantize_events_with_beats(events, CONSTANT_TEMPO_BEATS)

    assert quantized[0].subdivision == 1


def test_quantize_events_with_beats_raises_with_fewer_than_two_beats():
    with pytest.raises(ValueError, match="at least two"):
        quantize_events_with_beats([_event(0.0)], [CONSTANT_TEMPO_BEATS[0]])


def test_beat_anchored_position_to_seconds_round_trips_a_variable_tempo_position():
    # Same position produced by the tempo-change test above (measure 1,
    # beat 3, subdivision 2) must reconstruct back to exactly 1.4s.
    time = beat_anchored_position_to_seconds(VARIABLE_TEMPO_BEATS, measure=1, beat=3, subdivision=2)

    assert time == pytest.approx(1.4)


def test_beat_anchored_position_to_seconds_round_trips_an_extrapolated_before_first_position():
    time = beat_anchored_position_to_seconds(OFFSET_BEATS, measure=0, beat=4, subdivision=2)

    assert time == pytest.approx(2.25)


def test_beat_anchored_position_to_seconds_raises_with_fewer_than_two_beats():
    with pytest.raises(ValueError, match="at least two"):
        beat_anchored_position_to_seconds([CONSTANT_TEMPO_BEATS[0]], measure=1, beat=1, subdivision=0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_beat_mapping.py -v -k "with_beats or beat_anchored"`
Expected: FAIL/collection error - `quantize_events_with_beats`/`beat_anchored_position_to_seconds` don't exist yet.

- [ ] **Step 3: Implement**

In `backend/app/beat_mapping.py`, add the import and both functions:

```python
from app.timing import BeatPoint
```

```python
def _beat_period(beats: list[BeatPoint], index: int) -> float:
    """The local beat duration around beats[index]: the interval to its
    next point, or (if index is the last one) the interval from its
    previous point. Assumes beats is gapless - each entry exactly one
    beat after the previous, matching what LibrosaBeatDetector actually
    produces."""
    if index < len(beats) - 1:
        return beats[index + 1].source_time - beats[index].source_time
    return beats[index].source_time - beats[index - 1].source_time


def _locate(beats: list[BeatPoint], time: float) -> int:
    """Index of the last beat point at or before time, or 0 if time
    precedes every point (extrapolation is handled by the caller via
    ordinary offset arithmetic, not by this function)."""
    index = 0
    for i, beat in enumerate(beats):
        if beat.source_time <= time:
            index = i
        else:
            break
    return index


def _absolute_beat_index(beat: BeatPoint, beats_per_measure: int) -> int:
    return (beat.measure - 1) * beats_per_measure + (beat.beat - 1)


def quantize_events_with_beats(
    events: list[DrumEvent],
    beats: list[BeatPoint],
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> list[DrumEvent]:
    """Assigns measure/beat/subdivision using the LOCAL interval around
    the nearest real detected beat, instead of a single constant-BPM grid
    anchored at t=0 - see docs/ARCHITECTURE_V1.md's Timing model and
    docs/superpowers/plans/2026-09-21-beat-anchored-quantization.md for
    the worked examples this design is based on."""
    if len(beats) < 2:
        raise ValueError("quantize_events_with_beats requires at least two beats")

    quantized: list[DrumEvent] = []
    for event in events:
        i = _locate(beats, event.time)
        period = _beat_period(beats, i)
        subdivisions_from_i = round((event.time - beats[i].source_time) / period * subdivisions_per_beat)
        beat_offset, subdivision = divmod(subdivisions_from_i, subdivisions_per_beat)

        absolute_index = _absolute_beat_index(beats[i], beats_per_measure) + beat_offset
        measure = absolute_index // beats_per_measure + 1
        beat_in_measure = absolute_index % beats_per_measure + 1

        quantized.append(
            dataclasses.replace(event, measure=measure, beat=beat_in_measure, subdivision=subdivision)
        )
    return quantized


def beat_anchored_position_to_seconds(
    beats: list[BeatPoint],
    measure: int,
    beat: int,
    subdivision: int,
    beats_per_measure: int = DEFAULT_BEATS_PER_MEASURE,
    subdivisions_per_beat: int = DEFAULT_SUBDIVISIONS_PER_BEAT,
) -> float:
    """The exact inverse of quantize_events_with_beats: reconstructs the
    real-world time a musical position corresponds to, using the same
    local beat anchors quantization used - not a single global BPM. Used
    to compute quantization error (reconstructed time - event.time),
    mirroring how musical_position_to_seconds supports the constant-grid
    path's diagnostics today."""
    if len(beats) < 2:
        raise ValueError("beat_anchored_position_to_seconds requires at least two beats")

    target_absolute_index = (measure - 1) * beats_per_measure + (beat - 1)
    reference_absolute_index = _absolute_beat_index(beats[0], beats_per_measure)
    offset_from_first = target_absolute_index - reference_absolute_index

    ref = max(0, min(offset_from_first, len(beats) - 1))
    beat_delta = offset_from_first - ref
    period = _beat_period(beats, ref)

    return beats[ref].source_time + (beat_delta + subdivision / subdivisions_per_beat) * period
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_beat_mapping.py -v`
Expected: PASS (all tests in the file, including every pre-existing `quantize_events`/`musical_position_to_seconds` test - no regressions, since neither existing function was touched).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/beat_mapping.py backend/tests/test_beat_mapping.py
git commit -m "feat: add beat-anchored quantization using local beat-point intervals"
```

---

## Self-Review Notes

- **Spec coverage:** "sourceTime is unchanged" -> `test_quantize_events_with_beats_preserves_original_time`. "musicalPosition derives from local beat anchors" -> every quantized position comes from `beats[i]` (the nearest real point) and its own local `_beat_period`, never a global average. "variable beat durations work" -> `test_quantize_events_with_beats_uses_the_local_interval_during_a_tempo_change`, hand-verified before being written into the plan. "quantization error can be inspected" -> `beat_anchored_position_to_seconds` mirrors `musical_position_to_seconds`'s existing role exactly, round-trip-tested. "unit tests cover off-grid human timing and tempo variation" -> the snapping test and the tempo-change test respectively.
- **Scope check:** no `job_processor.py`/`Job`/API changes - confirmed this belongs to #43 (frontend/pipeline migration) and #44 (removing the old path), not this issue.
- **Correctness verified by hand before writing code, not after:** both the "non-zero first beat" and "variable tempo + round-trip" examples were computed by hand in the plan's design section and cross-checked against what the implementation should produce, including verifying the round-trip reconstruction returns the exact original time.
