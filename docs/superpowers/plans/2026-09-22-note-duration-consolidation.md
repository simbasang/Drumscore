# Musical Note-Duration Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the score domain model's hardcoded every-hit-is-a-16th-note representation with note durations derived from the gap to the next occupied rhythmic position (quarter/eighth/sixteenth etc.), so common grooves render as readable notation instead of a dense sixteenth grid with separate rests.

**Architecture:** `frontend/lib/score/grid.ts` already has a `consolidateRests` pass that merges runs of single-sixteenth rest slots into the fewest tied rest values, using a size table (`REST_SIZES_SIXTEENTHS`) with a metrical-alignment check (a candidate duration may only start on a position that's a multiple of its own length). This plan generalizes that same table/alignment rule to *notes*: a new `consolidateDurations` pass first extends each note to absorb as many of its immediately-following rest slots as the alignment rule allows (capped by the run of rests actually available before the next note or end of measure), then runs the existing `consolidateRests` on what's left over. `buildScore.ts` and `transformations.ts` switch from calling `consolidateRests` directly to calling `consolidateDurations`. `expandMeasure` (the inverse, used by edit operations) gets a one-line fix: it already correctly places a note back at its own single sixteenth index, but currently keeps that note's *old* (possibly multi-sixteenth) duration instead of resetting it to a single sixteenth, which would double-count duration once notes can span more than one slot.

**Tech Stack:** TypeScript, Jest (see `~/.claude/rules/testing.md` for this repo's global testing conventions — this plan follows AAA structure, `__tests__` placement, no new mocks needed since these are pure functions).

**Spec:** No separate spec/design doc — GitHub issue #51 (V1-018) is small enough that its acceptance criteria plus this plan's Architecture section fully define the scope. Relevant excerpts:
- Issue #51 acceptance criteria: quarter/eighth/sixteenth examples render with appropriate durations; simultaneous hits share duration; rests remain correct; no source timing is lost; unit fixtures cover common grooves.
- `docs/ARCHITECTURE_V1.md` "Editable score": the application-owned score supports note/rest durations; editor and renderer never operate directly on VexFlow structures.
- `PROJECT.md` Epic 4: "note-duration consolidation" is explicitly named as part of the Notation Engine 2.0 exit gate.

## Global Constraints

- Source audio time is authoritative: every `ScoreHit.time`/`sourceEventId` must survive this change completely unmodified — only the `duration` field on `ScoreNote`/`ScoreRest` slots changes, and which raw sixteenth-grid slots get merged into one.
- Preserve existing contracts: `consolidateRests`'s own current behavior and tests (grid.test.ts) must keep passing unchanged — it stays a "leave notes alone, merge rest runs" primitive; the new note-extension behavior is added as a separate layer on top, not by editing `consolidateRests` itself.
- A duration value may only be assigned starting at a metrically-aligned position: a candidate duration of length `D` sixteenths may only be used if the slot's own sixteenth-index is a multiple of `D` (same rule `consolidateRests` already applies to rests).
- No VexFlow/engraving-layer changes are needed: `buildStaveNote.ts` already reads `slot.duration` generically for both notes (`duration: slot.duration`) and rests (`` `${slot.duration}r` ``).
- Do not touch `backend/` — this is a pure frontend score-domain-model change (Epic 4, notation layer only).

---

## File Structure

- Modify `frontend/lib/score/grid.ts`: rename `REST_SIZES_SIXTEENTHS` → `DURATION_SIZES_SIXTEENTHS` (now used by both rests and notes); add new exported `consolidateDurations(slots: Slot[]): Slot[]`; fix `expandMeasure` to reset a placed note's duration back to `SLOT_DURATION`.
- Modify `frontend/lib/score/buildScore.ts`: call `consolidateDurations` instead of `consolidateRests`.
- Modify `frontend/lib/score/transformations.ts`: call `consolidateDurations` instead of `consolidateRests` in both `deleteHit` and `insertHit`.
- Modify `frontend/lib/score/__tests__/grid.test.ts`: update the renamed-constant-adjacent test comment (none needed — table is internal), add a `describe("consolidateDurations", ...)` block, add an `expandMeasure` regression test for the duration-reset fix.
- Modify `frontend/lib/score/__tests__/buildScore.test.ts`: update the one existing test whose expected output changes under the new behavior, add groove fixtures (quarter, eighth, mixed backbeat) per acceptance criteria.
- No changes needed to `frontend/lib/notation/buildStaveNote.ts`, `frontend/components/DrumScore.tsx`, or their tests — both already read `slot.duration` generically; verified in Task 6 by running the existing suite and a manual browser check.

---

### Task 1: Rename the duration-size table and add `consolidateDurations`

**Files:**
- Modify: `frontend/lib/score/grid.ts`
- Test: `frontend/lib/score/__tests__/grid.test.ts`

**Interfaces:**
- Consumes: existing `toSixteenthIndex(position: MusicalPosition): number`, `toPosition(measure: number, sixteenthIndex: number): MusicalPosition`, `consolidateRests(slots: Slot[]): Slot[]`, `generateId` (unused here), types `Slot`/`Measure`/`MusicalPosition` from `./types`.
- Produces: `export function consolidateDurations(slots: Slot[]): Slot[]` — later tasks (buildScore.ts, transformations.ts) call this instead of `consolidateRests`.

- [ ] **Step 1: Write the failing tests for `consolidateDurations`**

Add to `frontend/lib/score/__tests__/grid.test.ts` (add `consolidateDurations` to the existing import from `../grid`, alongside `consolidateRests, expandMeasure, toPosition, toSixteenthIndex`):

```ts
describe("consolidateDurations", () => {
  it("should extend a single note in an otherwise-empty measure into a whole note", () => {
    const slots: Measure = [
      note(1, 1, 0),
      ...Array.from({ length: 15 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 1),
      })),
    ];

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ type: "note", duration: "1" });
  });

  it("should turn four quarter-spaced hits into four quarter notes", () => {
    const slots: Measure = [0, 4, 8, 12].map((index) => note(1, ...positionParts(index)));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(4);
    expect(result.every((slot) => slot.type === "note" && slot.duration === "4")).toBe(true);
  });

  it("should turn eight eighth-spaced hits into eight eighth notes", () => {
    const slots: Measure = [0, 2, 4, 6, 8, 10, 12, 14].map((index) => note(1, ...positionParts(index)));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(8);
    expect(result.every((slot) => slot.type === "note" && slot.duration === "8")).toBe(true);
  });

  it("should leave adjacent sixteenth-spaced hits as sixteenth notes", () => {
    const slots: Measure = [0, 1, 2, 3].map((index) => note(1, ...positionParts(index)));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(4);
    expect(result.every((slot) => slot.type === "note" && slot.duration === "16")).toBe(true);
  });

  it("should cap a note's extension at the alignment boundary instead of overrunning into a misaligned duration", () => {
    // A note at sixteenth-index 2 (beat 1, subdivision 2) followed by rests to the
    // end of the measure can only become an eighth note (index 2 is a multiple of
    // 2 but not of 4/8/16), even though 13 trailing rests would otherwise fit a
    // much longer duration.
    const slots: Measure = [
      note(1, 1, 2),
      ...Array.from({ length: 13 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 3),
      })),
    ];

    const result = consolidateDurations(slots);

    expect(result[0]).toMatchObject({ type: "note", duration: "8" });
  });

  it("should preserve every hit's id, sourceEventId, and time when extending a note's duration", () => {
    const original = note(1, 1, 0);
    const slots: Measure = [
      original,
      ...Array.from({ length: 3 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 1),
      })),
    ];

    const result = consolidateDurations(slots);

    expect(result[0]).toMatchObject({ type: "note", duration: "4", hits: original.hits });
  });

  it("should not touch rests that never follow a note", () => {
    const slots: Measure = Array.from({ length: 16 }, (_, i) => ({
      type: "rest" as const,
      id: `r${i}`,
      duration: "16",
      position: toPosition(1, i),
    }));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ type: "rest", duration: "1" });
  });
});
```

Add this small helper near the top of the test file, right after the existing `note` helper — it turns a flat sixteenth-index into the `(beat, subdivision)` pair `note()` expects, since several of the new tests build notes from a list of raw indices:

```ts
function positionParts(sixteenthIndex: number): [beat: number, subdivision: number] {
  const position = toPosition(1, sixteenthIndex);
  return [position.beat, position.subdivision];
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest lib/score/__tests__/grid.test.ts -t consolidateDurations`
Expected: FAIL — `consolidateDurations` is not exported from `../grid` (TypeScript/Jest module error).

- [ ] **Step 3: Implement `consolidateDurations` in `grid.ts`**

In `frontend/lib/score/grid.ts`, rename the existing constant and update its one existing usage, then add the new function. The full intended file (existing `toSixteenthIndex`, `toPosition`, `consolidateRests`, `expandMeasure` bodies are unchanged except the rename and the `expandMeasure` fix from Task 2 — shown here is the diff-relevant portion):

```ts
// Largest-to-smallest so both consolidateRests and consolidateDurations always
// prefer the longest valid value, ordered with their duration in sixteenth-note
// units. Shared between rests and notes: the same "must start on a position
// that's a multiple of its own length" alignment rule applies to both.
const DURATION_SIZES_SIXTEENTHS: { duration: string; sixteenths: number }[] = [
  { duration: "1", sixteenths: 16 },
  { duration: "2", sixteenths: 8 },
  { duration: "4", sixteenths: 4 },
  { duration: "8", sixteenths: 2 },
  { duration: "16", sixteenths: 1 },
];
```

(replace every remaining reference to `REST_SIZES_SIXTEENTHS` in the file — there is exactly one, inside `consolidateRests` — with `DURATION_SIZES_SIXTEENTHS`).

Then add, after `consolidateRests`:

```ts
// Extends each note to absorb as many of its immediately-following rest slots
// as the alignment rule allows (same rule consolidateRests uses for rests: a
// candidate duration may only start on a position that's a multiple of its own
// length), then runs consolidateRests on whatever rests are left over. This is
// how "durations derived from occupied rhythmic positions" (V1-018/#51) works:
// a note's rendered duration is the gap to the next occupied position (or end
// of measure), quantized down to the largest metrically-valid value - not a
// fixed sixteenth.
export function consolidateDurations(slots: Slot[]): Slot[] {
  return consolidateRests(extendNoteDurations(slots));
}

function extendNoteDurations(slots: Slot[]): Slot[] {
  const result: Slot[] = [];
  let i = 0;

  while (i < slots.length) {
    const slot = slots[i];
    if (slot.type !== "note") {
      result.push(slot);
      i++;
      continue;
    }

    let restRun = 0;
    while (i + 1 + restRun < slots.length && slots[i + 1 + restRun].type === "rest") {
      restRun++;
    }

    const sixteenthIndex = toSixteenthIndex(slot.position);
    const capacity = 1 + restRun;
    // The smallest entry (1 sixteenth) always matches, since sixteenthIndex % 1
    // is always 0 and capacity is always >= 1 - .find() can never fall through.
    const size = DURATION_SIZES_SIXTEENTHS.find(
      ({ sixteenths }) => sixteenths <= capacity && sixteenthIndex % sixteenths === 0,
    )!;

    result.push({ ...slot, duration: size.duration });
    i += size.sixteenths;
  }

  return result;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest lib/score/__tests__/grid.test.ts`
Expected: PASS — all `consolidateDurations` tests pass, and every pre-existing `consolidateRests`/`toSixteenthIndex`/`toPosition`/`expandMeasure` test in the same file still passes unchanged (confirms the rename didn't break anything and `consolidateRests`'s own behavior is untouched).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/grid.ts frontend/lib/score/__tests__/grid.test.ts
git commit -m "$(cat <<'EOF'
feat: add consolidateDurations for note-duration consolidation

Extends each note to absorb its immediately-following rest slots (capped
by the same metrical-alignment rule consolidateRests already applies),
so a note's duration reflects the gap to the next occupied position
instead of always being a sixteenth.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9
EOF
)"
```

---

### Task 2: Fix `expandMeasure` to reset a note's duration when re-exploding

**Files:**
- Modify: `frontend/lib/score/grid.ts`
- Test: `frontend/lib/score/__tests__/grid.test.ts`

**Interfaces:**
- Consumes: `SLOT_DURATION` (existing constant, `"16"`), `toSixteenthIndex`, `toPosition` (existing).
- Produces: `expandMeasure`'s existing signature `(measure: Measure, measureNumber: number): Slot[]` is unchanged — only its internal duration-reset behavior changes. Task 3's edit-path callers (`transformations.ts`) rely on this being correct once notes can have durations longer than one sixteenth.

Context: once Task 1 lands, a `ScoreNote` can have `duration: "4"` (a quarter note) while still being placed at a single sixteenth index in `expandMeasure`'s one-slot-per-sixteenth output. `expandMeasure` already fills every *other* index with a fresh single-sixteenth rest, so if it also keeps the note's old multi-sixteenth `duration` value unchanged, the exploded measure double-counts: the note claims 4 sixteenths' worth of duration *and* 3 of those same sixteenth-index slots also get their own separate fresh rest. The fix is to reset the note's `duration` field back to `SLOT_DURATION` at the moment it's placed in the exploded array, matching what already happens conceptually for every other index (a fresh 16th slot).

- [ ] **Step 1: Write the failing test**

Add to `frontend/lib/score/__tests__/grid.test.ts`, inside the existing `describe("expandMeasure", ...)` block:

```ts
  it("should reset an extended note's duration back to a sixteenth when exploding it", () => {
    const quarterNote: ScoreNote = { ...note(4, 2, 0), duration: "4" };
    const measure: Measure = [quarterNote];

    const expanded = expandMeasure(measure, 4);

    expect(expanded).toHaveLength(16);
    expect(expanded[4]).toMatchObject({ type: "note", duration: "16", position: { measure: 4, beat: 2, subdivision: 0 } });
    expect(expanded.filter((slot) => slot.type === "rest")).toHaveLength(15);
    const totalSixteenths = expanded.reduce(
      (sum, slot) => sum + ({ "1": 16, "2": 8, "4": 4, "8": 2, "16": 1 }[slot.duration] ?? 0),
      0,
    );
    expect(totalSixteenths).toBe(16);
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx jest lib/score/__tests__/grid.test.ts -t "reset an extended note"`
Expected: FAIL — `expanded[4].duration` is `"4"` (the stale value) instead of `"16"`, and `totalSixteenths` is `19` (4 for the note + 15 separate fresh-rest sixteenths), not `16`.

- [ ] **Step 3: Fix `expandMeasure`**

In `frontend/lib/score/grid.ts`, change the one line in `expandMeasure` that copies the existing note into the map, from:

```ts
      bySixteenthIndex.set(toSixteenthIndex(slot.position), slot);
```

to:

```ts
      bySixteenthIndex.set(toSixteenthIndex(slot.position), { ...slot, duration: SLOT_DURATION });
```

Also update the function's doc comment (currently says durations "aren't consolidated across notes yet - that's V1-018/#51", which is now stale) to:

```ts
// Expands an already-consolidated measure back to one slot per sixteenth, so
// a transformation can edit a single slot before re-consolidating. Every note
// is reset to a single-sixteenth duration at its own index here - any longer
// duration it had (from consolidateDurations) only reflects trailing rests
// that get freshly rebuilt below, so keeping the old duration would
// double-count that span once notes can be longer than one sixteenth.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx jest lib/score/__tests__/grid.test.ts`
Expected: PASS — the new test passes, and every pre-existing `expandMeasure` test (including "should preserve an existing note at its own sixteenth index...", which used a plain 16th-duration note and so was already passing) still passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/grid.ts frontend/lib/score/__tests__/grid.test.ts
git commit -m "$(cat <<'EOF'
fix: reset extended note duration when re-exploding a measure

expandMeasure kept a note's possibly-multi-sixteenth duration while also
filling the sixteenths it spanned with separate fresh rests, double-
counting duration once notes can be longer than a sixteenth.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9
EOF
)"
```

---

### Task 3: Wire `consolidateDurations` into `buildScore.ts` and update its tests

**Files:**
- Modify: `frontend/lib/score/buildScore.ts`
- Test: `frontend/lib/score/__tests__/buildScore.test.ts`

**Interfaces:**
- Consumes: `consolidateDurations` from `./grid` (Task 1).
- Produces: `fromAnalysisEvents(events: AnalysisEvent[]): Score` keeps its existing signature; only the durations in its output change.

- [ ] **Step 1: Update the one existing test whose expected output changes, and add groove fixtures**

In `frontend/lib/score/__tests__/buildScore.test.ts`, replace the test named `"should place a single event in its slot and consolidate the remaining rests down to the fewest tied durations"` (the single kick-at-beat-1 case) — under the new behavior a lone note with nothing else in the measure now extends to a whole note, exactly mirroring the existing "entirely empty measure -> whole rest" test right above it:

```ts
  it("should extend a single event's note to fill the rest of an otherwise-empty measure", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 0.1, confidence: 0.8 }),
    ]);

    expect(score.measures[0]).toEqual([
      {
        type: "note",
        id: expect.any(String),
        position: { measure: 1, beat: 1, subdivision: 0 },
        duration: "1",
        hits: [
          {
            id: expect.any(String),
            sourceEventId: "a",
            time: 0.1,
            instrument: "kick",
            confidence: 0.8,
            provenance: "drumscript",
          },
        ],
      },
    ]);
  });
```

Then add new tests, right after it, covering the acceptance criteria's named grooves:

```ts
  it("should render a four-on-the-floor kick groove as quarter notes", () => {
    const score = fromAnalysisEvents(
      [1, 2, 3, 4].map((beat) => event({ id: `k${beat}`, instrument: "kick", beat, subdivision: 0 })),
    );

    expect(score.measures[0]).toHaveLength(4);
    expect(score.measures[0].every((slot) => slot.type === "note" && slot.duration === "4")).toBe(true);
  });

  it("should render a steady eighth-note hi-hat groove as eighth notes", () => {
    const positions = [0, 1, 2, 3].flatMap((beat) => [
      { beat: beat + 1, subdivision: 0 },
      { beat: beat + 1, subdivision: 2 },
    ]);
    const score = fromAnalysisEvents(
      positions.map((p, i) => event({ id: `h${i}`, instrument: "hihat_closed", ...p })),
    );

    expect(score.measures[0]).toHaveLength(8);
    expect(score.measures[0].every((slot) => slot.type === "note" && slot.duration === "8")).toBe(true);
  });

  it("should render a sixteenth-note hi-hat groove as sixteenth notes with no consolidation", () => {
    const score = fromAnalysisEvents(
      Array.from({ length: 16 }, (_, subdivision) =>
        event({ id: `h${subdivision}`, instrument: "hihat_closed", beat: Math.floor(subdivision / 4) + 1, subdivision: subdivision % 4 }),
      ),
    );

    expect(score.measures[0]).toHaveLength(16);
    expect(score.measures[0].every((slot) => slot.type === "note" && slot.duration === "16")).toBe(true);
  });

  it("should render a kick-and-backbeat-snare groove as quarter notes on the hits and a consolidated rest between", () => {
    const score = fromAnalysisEvents([
      event({ id: "k1", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "s1", instrument: "snare", beat: 2, subdivision: 0 }),
    ]);

    expect(score.measures[0]).toEqual([
      expect.objectContaining({ type: "note", duration: "4", position: { measure: 1, beat: 1, subdivision: 0 } }),
      expect.objectContaining({ type: "note", duration: "4", position: { measure: 1, beat: 2, subdivision: 0 } }),
      expect.objectContaining({ type: "rest", duration: "2", position: { measure: 1, beat: 3, subdivision: 0 } }),
    ]);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest lib/score/__tests__/buildScore.test.ts`
Expected: FAIL — the updated/new tests fail because `fromAnalysisEvents` still calls `consolidateRests` (every note duration is still `"16"`).

- [ ] **Step 3: Switch `buildScore.ts` to `consolidateDurations`**

In `frontend/lib/score/buildScore.ts`, change the import on line 2 from:

```ts
import { BEATS_PER_MEASURE, consolidateRests, SLOT_DURATION, SUBDIVISIONS_PER_BEAT } from "./grid";
```

to:

```ts
import { BEATS_PER_MEASURE, consolidateDurations, SLOT_DURATION, SUBDIVISIONS_PER_BEAT } from "./grid";
```

and change the call on line 45 from:

```ts
    measures.push(consolidateRests(slots));
```

to:

```ts
    measures.push(consolidateDurations(slots));
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest lib/score/__tests__/buildScore.test.ts`
Expected: PASS — all tests in the file pass, including the unchanged `"should always account for exactly one measure's worth of duration, regardless of note placement"` invariant test (still holds: consolidation only redistributes which slots carry which duration, never changes the total).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/buildScore.ts frontend/lib/score/__tests__/buildScore.test.ts
git commit -m "$(cat <<'EOF'
feat: build score notes with consolidated durations, not fixed sixteenths

fromAnalysisEvents now calls consolidateDurations so common grooves
(four-on-the-floor kicks, steady eighth-note hi-hats, backbeat patterns)
render with their natural quarter/eighth/sixteenth durations instead of
a dense sixteenth-note grid.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9
EOF
)"
```

---

### Task 4: Wire `consolidateDurations` into `transformations.ts`

**Files:**
- Modify: `frontend/lib/score/transformations.ts`
- Test: `frontend/lib/score/__tests__/transformations.test.ts`

**Interfaces:**
- Consumes: `consolidateDurations` from `./grid` (Task 1), `expandMeasure` (existing, fixed in Task 2).
- Produces: `deleteHit`, `moveHit`, `insertHit` keep their existing signatures and behavior from the caller's perspective — edits made after this task will consolidate extended note durations too (e.g. deleting a hit that was splitting two runs of rests may let a neighboring note extend further).

- [ ] **Step 1: Write a failing test proving edits now produce consolidated durations**

Add to `frontend/lib/score/__tests__/transformations.test.ts`, in a new `describe` block at the end of the file:

```ts
describe("duration consolidation after edits", () => {
  it("should extend a note's duration after deleting a hit that used to split it from trailing rests", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "snare", beat: 1, subdivision: 1 }),
    ]);
    const snareHitId = hitsAt(score, 1, 1, 1)[0].id;

    const updated = deleteHit(score, snareHitId);

    const kickSlot = updated.measures[0].find((s) => s.position.beat === 1 && s.position.subdivision === 0);
    expect(kickSlot).toMatchObject({ type: "note", duration: "1" });
  });

  it("should give a newly-added hit a consolidated duration when it fills the rest of the measure", () => {
    const score = fromAnalysisEvents([]);

    const updated = addHit(score, { measure: 1, beat: 1, subdivision: 0 }, "kick");

    const slot = updated.measures[0].find((s) => s.position.beat === 1 && s.position.subdivision === 0);
    expect(slot).toMatchObject({ type: "note", duration: "1" });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest lib/score/__tests__/transformations.test.ts -t "duration consolidation after edits"`
Expected: FAIL — both new tests see `duration: "16"` instead of `"1"`, since `deleteHit`/`insertHit` still call `consolidateRests`.

- [ ] **Step 3: Switch `transformations.ts` to `consolidateDurations`**

In `frontend/lib/score/transformations.ts`, change the import on line 2 from:

```ts
import { consolidateRests, expandMeasure, SLOT_DURATION, toSixteenthIndex } from "./grid";
```

to:

```ts
import { consolidateDurations, expandMeasure, SLOT_DURATION, toSixteenthIndex } from "./grid";
```

Change the call inside `deleteHit` (currently `return consolidateRests(updated);`) to:

```ts
    return consolidateDurations(updated);
```

Change the call inside `insertHit` (currently `return consolidateRests(expanded);`) to:

```ts
    return consolidateDurations(expanded);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest lib/score/__tests__/transformations.test.ts`
Expected: PASS — the two new tests pass, and every pre-existing test in the file (`addHit`, `deleteHit`, `moveHit`, `changeInstrument`, "source link preservation") still passes unchanged, since none of them assert on `duration` — they only assert on `ScoreHit` fields (id/sourceEventId/time/instrument/provenance), which this change never touches.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/transformations.ts frontend/lib/score/__tests__/transformations.test.ts
git commit -m "$(cat <<'EOF'
feat: consolidate note durations after add/delete/move edits

deleteHit and insertHit now call consolidateDurations instead of
consolidateRests, so edits keep the score's note durations consolidated
instead of leaving newly-adjacent notes stuck at a sixteenth.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9
EOF
)"
```

---

### Task 5: Full verification pass (tests, lint, typecheck, manual render check)

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && npx jest`
Expected: PASS — every test file in `frontend/`, including `components/__tests__/DrumScore.test.tsx` (unmodified — `buildStaveNote.ts` already reads `slot.duration` generically, and none of its assertions depend on every note being a sixteenth).

- [ ] **Step 2: Run lint and typecheck**

Run: `cd frontend && npm run lint && npx tsc --noEmit`
Expected: PASS — no new lint or type errors. (If the project's `package.json` uses a different script name for typecheck, e.g. `npm run typecheck`, use that instead — check `frontend/package.json`'s `scripts` block first.)

- [ ] **Step 3: Manually verify rendering in a real browser**

Per this project's CLAUDE.md working method, UI/rendering changes must be exercised in a real browser, not just asserted via jsdom tests (VexFlow's `Beam.generateBeams` and `Formatter` layout behavior with mixed quarter/eighth/sixteenth durations in the same measure is exactly the kind of thing jsdom-based tests can miss visually even while passing).

- Start the dev server: `cd frontend && npm run dev`
- Submit or load a job whose transcribed groove includes a mix of on-the-beat kicks and steady eighth/sixteenth hi-hats (or, if no real job is readily available, temporarily hardcode a `DrumScore` test render via the existing dev harness/page that already renders it — check `frontend/app/` for the page that mounts `DrumScore`).
- Confirm: quarter-note kicks render as single quarter-note stems (not four tied/separate sixteenths), eighth-note hi-hats render beamed correctly in pairs, rests between hits render as the expected consolidated rest values, and no VexFlow console errors/warnings appear.
- Stop the dev server when done.

- [ ] **Step 4: No commit for this task** (verification only — proceed to Task 6 if everything above passed; if anything failed, fix it under the task that introduced the regression and re-run this task's steps before continuing).

---

### Task 6: Update the stale technical-debt breadcrumb and open the PR

**Files:**
- Modify: `TECHNICAL_DEBT.md` (only if the grid.ts comment fix in Task 2 didn't already cover every mention — search first) and any other stale "V1-018" reference found.

**Interfaces:** none — documentation/process only.

- [ ] **Step 1: Search for any other stale references to this being future work**

Run: `cd /d/programmering/Drumscore && grep -rn "V1-018" --include=*.ts --include=*.md .`

Expected: only the `grid.ts` comment already fixed in Task 2's Step 3, plus this plan file itself and the GitHub issue. If `grep` finds any other stale "not yet implemented" reference (e.g. in `TECHNICAL_DEBT.md` or `PROJECT.md`), update it to reflect that note-duration consolidation is now implemented — but do not mark Epic 4's exit gate as met, since issues #52/#53/#72/#73 are still open.

- [ ] **Step 2: Push the branch and open the PR**

```bash
git push -u origin v1-018_note-duration-consolidation
gh pr create --title "V1-018: Musical note-duration consolidation" --body "$(cat <<'EOF'
## Summary
- Replaces the score domain model's hardcoded every-hit-is-a-16th-note representation with durations derived from the gap to the next occupied rhythmic position, quantized to the largest metrically-aligned value (whole/half/quarter/eighth/sixteenth).
- Adds `consolidateDurations` in `frontend/lib/score/grid.ts`, built on top of the existing `consolidateRests` (which keeps its own behavior/tests unchanged - it stays a "leave notes alone" rest-only primitive).
- Fixes a latent double-counting bug in `expandMeasure`: it kept a note's old (possibly multi-sixteenth) duration while also filling the sixteenths it spanned with fresh separate rests. Fixed by resetting a note's duration to a single sixteenth when it's re-exploded for editing.
- Wires the new consolidation into both the build path (`buildScore.ts`) and the edit path (`transformations.ts`'s `deleteHit`/`insertHit`), so manual corrections keep durations consolidated too.

## Root cause / investigation notes
`buildScore.ts` previously hardcoded `duration: SLOT_DURATION` ("16") on every `ScoreNote` unconditionally - there was no duration inference at all, only rest consolidation (`consolidateRests`, from MVP-011's legacy `buildScore.ts`, carried over in V1-017's score-domain-model rewrite). `grid.ts`'s own `expandMeasure` doc comment already flagged this exact gap: "durations aren't consolidated across notes yet - that's V1-018/#51".

## Test plan
- [x] `grid.test.ts`: new `consolidateDurations` unit tests (whole-note extension, quarter/eighth/sixteenth grooves, alignment-boundary capping, hit-field preservation, rest-only runs untouched) plus an `expandMeasure` regression test for the duration-reset fix.
- [x] `buildScore.test.ts`: updated the one test whose expected output changes (a lone note in an empty measure now extends to a whole note), added four-on-the-floor / eighth-note-hihat / sixteenth-note-hihat / backbeat groove fixtures.
- [x] `transformations.test.ts`: new tests proving `deleteHit`/`addHit` produce consolidated durations.
- [x] Full frontend suite (`npx jest`), lint, and `tsc --noEmit` all green.
- [x] Manually verified rendering in a real browser (dev server) with a mixed quarter/eighth/sixteenth groove - no VexFlow console errors, correct beaming and rest values.

## Scope notes
No backend changes. No VexFlow/engraving-layer code changes needed (`buildStaveNote.ts` already reads `slot.duration` generically). Beam grouping, hi-hat open/closed notation, and dynamic layout are separate Epic 4 issues (#52/#53/#72/#73), not touched here.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9
EOF
)"
```

- [ ] **Step 3: Report to the user and stop**

Summarize what changed, link the PR, and wait for merge confirmation per this repo's established per-issue workflow — do not start the next Epic 4 issue automatically.

---

## Self-Review Notes

- **Spec coverage:** "Quarter/eighth/sixteenth examples render with appropriate durations" → Task 3's groove fixtures. "Simultaneous hits share duration" → already guaranteed structurally (one `ScoreNote` per occupied position, one `duration` field shared by all its `hits`) and covered by existing `buildScore.test.ts` tests unaffected by this change; no separate task needed. "Rests remain correct" → Task 1's "should not touch rests that never follow a note" test plus Task 3's backbeat-groove test asserting the exact leftover rest value. "No source timing is lost" → Task 1's hit-field-preservation test plus Task 4's edit-path tests (which go through `ScoreHit`, never touched by duration logic). "Unit fixtures cover common grooves" → Task 3's four-on-the-floor/eighth-hihat/sixteenth-hihat/backbeat fixtures.
- **Placeholder scan:** no TBD/TODO markers; every step has literal code or an exact shell command.
- **Type consistency:** `consolidateDurations(slots: Slot[]): Slot[]` matches its one call site's expected signature in both `buildScore.ts` (replacing `consolidateRests(slots)`) and `transformations.ts` (replacing `consolidateRests(updated)` / `consolidateRests(expanded)`) - all three already pass a `Slot[]`. `DURATION_SIZES_SIXTEENTHS` fully replaces `REST_SIZES_SIXTEENTHS` with no remaining references to the old name (verified by the search in Task 6, Step 1, which also catches any doc/comment drift).
