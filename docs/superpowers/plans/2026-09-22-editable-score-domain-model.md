# Editable Score Domain Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `frontend/lib/score/`, an application-owned, VexFlow-free score domain model (durations, rests, simultaneous hits, source-event links, confidence/provenance) with construction from `AnalysisEvent[]`, add/delete/move/change-instrument transformations, and JSON serialization — then repoint the existing engraving path (`buildStaveNote.ts`, `DrumScore.tsx`) at it.

**Architecture:** Promote the existing `buildMeasures`/`SlotSpec` grid-grouping logic (`frontend/lib/notation/buildScore.ts`) into a typed domain model split across four small modules — `id.ts` (id generation), `grid.ts` (16th-grid position math + rest consolidation, reusable by both construction and edits), `buildScore.ts` (`AnalysisEvent[] → Score`), `transformations.ts` (hit-level edits) — plus `serialization.ts`. The old `lib/notation/buildScore.ts` is deleted once `buildStaveNote.ts` and `DrumScore.tsx` are repointed at the new types.

**Tech Stack:** TypeScript, Jest, React Testing Library (component test only, unchanged), no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-22-editable-score-domain-model-design.md`

## Global Constraints

- No VexFlow import anywhere under `frontend/lib/score/`.
- Every `ScoreHit`'s `sourceEventId`/`time` are set once at construction and never rewritten by any transformation except the one operating on that exact hit (`moveHit` relocates position but keeps the same hit record's `id`/`sourceEventId`/`time`/`confidence`/`provenance`; `changeInstrument` only touches `instrument`).
- Every hit produced by construction preserves its own source event, even when it shares an instrument and position with another hit — construction never drops or merges events (this is a deliberate change from the old `buildMeasures`, which silently deduplicated identical-instrument hits at construction time; deduplication for rendering purposes now happens only in `buildStaveNote.ts`, since collapsing two hits into one VexFlow notehead is a rendering concern, not a data-loss-tolerant one).
- Transformations operate at 16th-grid slot granularity and never add or remove measures.
- Manually added hits (`addHit`) get `sourceEventId: null`, `time: null`, `confidence: null`, `provenance: "manual"`.
- All new modules are plain functions over plain interfaces (no classes), matching the existing codebase's functional style.
- Jest tests: AAA structure (arrange/act/assert, blank line between), `describe`/`it("should ...")` naming, per `~/.claude/rules/testing.md`.

---

### Task 1: Score id generator

**Files:**
- Create: `frontend/lib/score/id.ts`
- Test: `frontend/lib/score/__tests__/id.test.ts`

**Interfaces:**
- Produces: `generateId(prefix: string): string` — used by every later task to stamp `ScoreNote`/`ScoreRest`/`ScoreHit` ids.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/score/__tests__/id.test.ts
import { generateId } from "../id";

describe("generateId", () => {
  it("should prefix the generated id with the given prefix", () => {
    const id = generateId("note");

    expect(id).toMatch(/^note-/);
  });

  it("should return a different id on each call", () => {
    const first = generateId("hit");
    const second = generateId("hit");

    expect(first).not.toBe(second);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm test -- id.test.ts` (from `frontend/`)
Expected: FAIL — `Cannot find module '../id'`

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/score/id.ts
let counter = 0;

export function generateId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- id.test.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/id.ts frontend/lib/score/__tests__/id.test.ts
git commit -m "feat: add score domain model id generator"
```

---

### Task 2: Thread confidence/provenance through AnalysisEvent

The backend's `GET /api/jobs/{id}/analysis` response already includes `confidence` and `provenance` on every event (`backend/app/api/jobs.py`'s `DrumEventResponse`), but the frontend's `AnalysisEvent` type drops both. This task closes that gap so Task 4 has real data to carry into the domain model, and fixes the two existing test fixtures that build `AnalysisEvent` literals so the tree stays green.

**Files:**
- Modify: `frontend/lib/api/jobs.ts:36-43` (the `AnalysisEvent` interface)
- Modify: `frontend/lib/notation/__tests__/buildScore.test.ts:4-14` (the local `event()` helper)
- Modify: `frontend/components/__tests__/DrumScore.test.tsx:6-16` (the local `event()` helper)

**Interfaces:**
- Produces: `AnalysisEvent.confidence: number | null`, `AnalysisEvent.provenance: string | null` — consumed by Task 4's `fromAnalysisEvents`.

- [ ] **Step 1: Add the fields to `AnalysisEvent`**

In `frontend/lib/api/jobs.ts`, change:

```ts
export interface AnalysisEvent {
  id: string;
  time: number;
  instrument: DrumInstrument;
  measure: number | null;
  beat: number | null;
  subdivision: number | null;
}
```

to:

```ts
export interface AnalysisEvent {
  id: string;
  time: number;
  instrument: DrumInstrument;
  confidence: number | null;
  provenance: string | null;
  measure: number | null;
  beat: number | null;
  subdivision: number | null;
}
```

- [ ] **Step 2: Run the typecheck to see it fail**

Run: `npx tsc --noEmit` (from `frontend/`)
Expected: FAIL — both `event()` helpers below report their return object is missing `confidence` and `provenance`.

- [ ] **Step 3: Fix both existing test fixtures**

In `frontend/lib/notation/__tests__/buildScore.test.ts`, change the `event()` helper:

```ts
function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    measure: 1,
    beat: 1,
    subdivision: 0,
    ...overrides,
  };
}
```

Apply the identical change to the `event()` helper in `frontend/components/__tests__/DrumScore.test.tsx`.

- [ ] **Step 4: Run the typecheck and full frontend suite to verify green**

Run: `npx tsc --noEmit && npm test`
Expected: PASS — typecheck clean, all existing tests still pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api/jobs.ts frontend/lib/notation/__tests__/buildScore.test.ts frontend/components/__tests__/DrumScore.test.tsx
git commit -m "feat: thread confidence and provenance through AnalysisEvent"
```

---

### Task 3: Score types

Pure type declarations — scaffolding for Task 4 onward, no standalone test (nothing to unit test in an interface; every field is exercised by Task 4+'s tests).

**Files:**
- Create: `frontend/lib/score/types.ts`

**Interfaces:**
- Produces: `MusicalPosition`, `ScoreHit`, `ScoreNote`, `ScoreRest`, `Slot`, `Measure`, `Score`, `Provenance` — consumed by every subsequent task.

- [ ] **Step 1: Write the types**

```ts
// frontend/lib/score/types.ts
import type { DrumInstrument } from "@/lib/api/jobs";

export type Provenance = string;

export interface MusicalPosition {
  measure: number;
  beat: number;
  subdivision: number;
}

export interface ScoreHit {
  id: string;
  sourceEventId: string | null;
  time: number | null;
  instrument: DrumInstrument;
  confidence: number | null;
  provenance: Provenance;
}

export interface ScoreNote {
  type: "note";
  id: string;
  position: MusicalPosition;
  duration: string;
  hits: ScoreHit[];
}

export interface ScoreRest {
  type: "rest";
  id: string;
  position: MusicalPosition;
  duration: string;
}

export type Slot = ScoreNote | ScoreRest;
export type Measure = Slot[];

export interface Score {
  measures: Measure[];
}
```

- [ ] **Step 2: Run the typecheck to verify the file compiles standalone**

Run: `npx tsc --noEmit`
Expected: PASS — no consumers yet, so this step only catches a typo in the file itself.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/score/types.ts
git commit -m "feat: add score domain model types"
```

---

### Task 4: 16th-grid position math and rest consolidation

Extracted as its own module because both construction (Task 5) and transformations (Task 6) need it: converting a musical position to/from a flat 0-15 index within a measure, merging a run of single-sixteenth rests into the fewest tied durations, and expanding an already-consolidated measure back out to 16 flat slots (notes keep their slot, gaps become fresh single-sixteenth rests) so an edit can be applied at slot granularity before re-consolidating.

**Files:**
- Create: `frontend/lib/score/grid.ts`
- Test: `frontend/lib/score/__tests__/grid.test.ts`

**Interfaces:**
- Consumes: `Measure`, `MusicalPosition`, `ScoreNote`, `Slot` (Task 3); `generateId` (Task 1).
- Produces: `BEATS_PER_MEASURE = 4`, `SUBDIVISIONS_PER_BEAT = 4`, `SLOT_DURATION = "16"`, `toSixteenthIndex(position: MusicalPosition): number`, `toPosition(measure: number, sixteenthIndex: number): MusicalPosition`, `consolidateRests(slots: Slot[]): Slot[]`, `expandMeasure(measure: Measure, measureNumber: number): Slot[]` (always length 16) — consumed by Task 5 and Task 6.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/score/__tests__/grid.test.ts
import { consolidateRests, expandMeasure, toPosition, toSixteenthIndex } from "../grid";
import type { Measure, ScoreNote } from "../types";

function note(measure: number, beat: number, subdivision: number): ScoreNote {
  return {
    type: "note",
    id: "n",
    position: { measure, beat, subdivision },
    duration: "16",
    hits: [
      {
        id: "h",
        sourceEventId: "e",
        time: 0,
        instrument: "kick",
        confidence: null,
        provenance: "drumscript",
      },
    ],
  };
}

describe("toSixteenthIndex", () => {
  it("should convert beat 1 subdivision 0 to index 0", () => {
    const index = toSixteenthIndex({ measure: 1, beat: 1, subdivision: 0 });

    expect(index).toBe(0);
  });

  it("should convert beat 2 subdivision 1 to index 5", () => {
    const index = toSixteenthIndex({ measure: 1, beat: 2, subdivision: 1 });

    expect(index).toBe(5);
  });

  it("should convert beat 4 subdivision 3 to index 15", () => {
    const index = toSixteenthIndex({ measure: 1, beat: 4, subdivision: 3 });

    expect(index).toBe(15);
  });
});

describe("toPosition", () => {
  it("should round-trip through toSixteenthIndex for every index in a measure", () => {
    for (let index = 0; index < 16; index++) {
      const position = toPosition(3, index);

      expect(position.measure).toBe(3);
      expect(toSixteenthIndex(position)).toBe(index);
    }
  });
});

describe("consolidateRests", () => {
  it("should merge sixteen individual rests into a single whole rest", () => {
    const slots: Measure = Array.from({ length: 16 }, (_, i) => ({
      type: "rest" as const,
      id: `r${i}`,
      duration: "16",
      position: toPosition(1, i),
    }));

    const result = consolidateRests(slots);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ type: "rest", duration: "1" });
  });

  it("should leave a note slot unchanged", () => {
    const slots: Measure = [note(1, 1, 0)];

    const result = consolidateRests(slots);

    expect(result).toEqual([note(1, 1, 0)]);
  });

  it("should merge the rests around an untouched note down to the fewest tied durations", () => {
    const slots: Measure = [
      note(1, 1, 0),
      ...Array.from({ length: 15 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 1),
      })),
    ];

    const result = consolidateRests(slots);

    expect(result.map((slot) => slot.duration)).toEqual(["16", "16", "8", "4", "2"]);
  });
});

describe("expandMeasure", () => {
  it("should return sixteen single-sixteenth rest slots for a measure with no notes", () => {
    const expanded = expandMeasure([], 2);

    expect(expanded).toHaveLength(16);
    expect(expanded.every((slot) => slot.type === "rest" && slot.duration === "16")).toBe(true);
    expect(expanded[0].position).toEqual({ measure: 2, beat: 1, subdivision: 0 });
  });

  it("should preserve an existing note at its own sixteenth index and fill the rest with single-sixteenth rests", () => {
    const measure: Measure = [note(4, 2, 1)];

    const expanded = expandMeasure(measure, 4);

    expect(expanded).toHaveLength(16);
    expect(expanded[5]).toMatchObject({ type: "note", position: { measure: 4, beat: 2, subdivision: 1 } });
    expect(expanded.filter((slot) => slot.type === "rest")).toHaveLength(15);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- grid.test.ts`
Expected: FAIL — `Cannot find module '../grid'`

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/score/grid.ts
import { generateId } from "./id";
import type { Measure, MusicalPosition, Slot } from "./types";

export const BEATS_PER_MEASURE = 4;
export const SUBDIVISIONS_PER_BEAT = 4;
export const SLOT_DURATION = "16";
const SLOTS_PER_MEASURE = BEATS_PER_MEASURE * SUBDIVISIONS_PER_BEAT;

// Largest-to-smallest so consolidateRests always prefers the longest valid
// rest value, ordered with their duration in sixteenth-note units.
const REST_SIZES_SIXTEENTHS: { duration: string; sixteenths: number }[] = [
  { duration: "1", sixteenths: 16 },
  { duration: "2", sixteenths: 8 },
  { duration: "4", sixteenths: 4 },
  { duration: "8", sixteenths: 2 },
  { duration: "16", sixteenths: 1 },
];

export function toSixteenthIndex(position: MusicalPosition): number {
  return (position.beat - 1) * SUBDIVISIONS_PER_BEAT + position.subdivision;
}

export function toPosition(measure: number, sixteenthIndex: number): MusicalPosition {
  return {
    measure,
    beat: Math.floor(sixteenthIndex / SUBDIVISIONS_PER_BEAT) + 1,
    subdivision: sixteenthIndex % SUBDIVISIONS_PER_BEAT,
  };
}

// Merges each run of consecutive single-sixteenth rests into the fewest rest
// values that tie together correctly, each aligned so its start position is
// a multiple of its own duration (e.g. a half rest only ever starts on beat
// 1 or 3 of a 4/4 measure) - the engraving convention that keeps rests
// readable instead of an arbitrary run of 16th rests.
export function consolidateRests(slots: Slot[]): Slot[] {
  const result: Slot[] = [];
  let i = 0;

  while (i < slots.length) {
    if (slots[i].type === "note") {
      result.push(slots[i]);
      i++;
      continue;
    }

    let runLength = 0;
    while (i + runLength < slots.length && slots[i + runLength].type === "rest") {
      runLength++;
    }

    const measure = slots[i].position.measure;
    let sixteenthIndex = toSixteenthIndex(slots[i].position);
    let remaining = runLength;
    while (remaining > 0) {
      // The smallest entry (a 16th rest, 1 sixteenth long) always matches
      // here, since sixteenthIndex % 1 is always 0 - .find() can never fall
      // through without a match while remaining > 0.
      const size = REST_SIZES_SIXTEENTHS.find(
        ({ sixteenths }) => sixteenths <= remaining && sixteenthIndex % sixteenths === 0,
      )!;
      result.push({
        type: "rest",
        id: generateId("rest"),
        duration: size.duration,
        position: toPosition(measure, sixteenthIndex),
      });
      sixteenthIndex += size.sixteenths;
      remaining -= size.sixteenths;
    }

    i += runLength;
  }

  return result;
}

// Expands an already-consolidated measure back to one slot per sixteenth,
// so a transformation can edit a single slot before re-consolidating. Every
// note in `measure` occupies exactly one sixteenth (durations aren't
// consolidated across notes yet - that's V1-018/#51), so this only needs to
// place each note at its own index and fill every other index with a fresh
// single-sixteenth rest; existing rest slots in `measure` are discarded and
// rebuilt, since consolidateRests will regenerate them anyway.
export function expandMeasure(measure: Measure, measureNumber: number): Slot[] {
  const bySixteenthIndex = new Map<number, Slot>();
  for (const slot of measure) {
    if (slot.type === "note") {
      bySixteenthIndex.set(toSixteenthIndex(slot.position), slot);
    }
  }

  return Array.from({ length: SLOTS_PER_MEASURE }, (_, index) => {
    const existing = bySixteenthIndex.get(index);
    if (existing) {
      return existing;
    }
    return {
      type: "rest",
      id: generateId("rest"),
      duration: SLOT_DURATION,
      position: toPosition(measureNumber, index),
    };
  });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- grid.test.ts`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/grid.ts frontend/lib/score/__tests__/grid.test.ts
git commit -m "feat: add score domain model 16th-grid position math"
```

---

### Task 5: Score construction from AnalysisEvent

**Files:**
- Create: `frontend/lib/score/buildScore.ts`
- Test: `frontend/lib/score/__tests__/buildScore.test.ts`

**Interfaces:**
- Consumes: `AnalysisEvent` (`@/lib/api/jobs`, Task 2); `BEATS_PER_MEASURE`, `SUBDIVISIONS_PER_BEAT`, `SLOT_DURATION`, `consolidateRests` (Task 4); `generateId` (Task 1); `Measure`, `MusicalPosition`, `Score`, `ScoreNote`, `Slot` (Task 3).
- Produces: `fromAnalysisEvents(events: AnalysisEvent[]): Score` — consumed by Task 6's tests, Task 7's `serialization.test.ts`, and Task 9's `DrumScore.tsx`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/score/__tests__/buildScore.test.ts
import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "../buildScore";
import type { Measure } from "../types";

function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    measure: 1,
    beat: 1,
    subdivision: 0,
    ...overrides,
  };
}

const DURATION_SIXTEENTHS: Record<string, number> = { "1": 16, "2": 8, "4": 4, "8": 2, "16": 1 };

function totalSixteenths(measure: Measure): number {
  return measure.reduce((sum, slot) => sum + DURATION_SIXTEENTHS[slot.duration], 0);
}

describe("fromAnalysisEvents", () => {
  it("should return no measures for no events", () => {
    const score = fromAnalysisEvents([]);

    expect(score).toEqual({ measures: [] });
  });

  it("should consolidate an entirely empty measure into a single whole rest", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", measure: 2, beat: 1, subdivision: 0 })]);

    expect(score.measures[0]).toEqual([
      { type: "rest", id: expect.any(String), duration: "1", position: { measure: 1, beat: 1, subdivision: 0 } },
    ]);
  });

  it("should place a single event in its slot and consolidate the remaining rests down to the fewest tied durations", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 0.1, confidence: 0.8 }),
    ]);

    expect(score.measures[0]).toEqual([
      {
        type: "note",
        id: expect.any(String),
        position: { measure: 1, beat: 1, subdivision: 0 },
        duration: "16",
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
      { type: "rest", id: expect.any(String), duration: "16", position: { measure: 1, beat: 1, subdivision: 1 } },
      { type: "rest", id: expect.any(String), duration: "8", position: { measure: 1, beat: 1, subdivision: 2 } },
      { type: "rest", id: expect.any(String), duration: "4", position: { measure: 1, beat: 2, subdivision: 0 } },
      { type: "rest", id: expect.any(String), duration: "2", position: { measure: 1, beat: 3, subdivision: 0 } },
    ]);
  });

  it("should combine simultaneous instruments into a single note with multiple hits", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "hihat_closed", beat: 1, subdivision: 0 }),
    ]);

    const note = score.measures[0][0] as { type: string; hits: { instrument: string }[] };
    expect(note.type).toBe("note");
    expect(note.hits.map((hit) => hit.instrument)).toEqual(["kick", "hihat_closed"]);
  });

  it("should preserve both hits, with their own source links, when two events share an instrument and position", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "kick", beat: 1, subdivision: 0 }),
    ]);

    const note = score.measures[0][0] as { type: string; hits: { sourceEventId: string | null }[] };
    expect(note.type).toBe("note");
    expect(note.hits.map((hit) => hit.sourceEventId)).toEqual(["a", "b"]);
  });

  it("should keep a note at its correct metric position even after leading/trailing rests are consolidated", () => {
    const score = fromAnalysisEvents([event({ instrument: "snare", beat: 2, subdivision: 1 })]);

    const noteSlot = score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot?.position).toEqual({ measure: 1, beat: 2, subdivision: 1 });
  });

  it("should always account for exactly one measure's worth of duration, regardless of note placement", () => {
    const placements = [
      [{ beat: 1, subdivision: 0 }],
      [{ beat: 1, subdivision: 0 }, { beat: 3, subdivision: 0 }],
      [{ beat: 1, subdivision: 0 }, { beat: 2, subdivision: 0 }, { beat: 4, subdivision: 3 }],
    ];

    for (const placement of placements) {
      const score = fromAnalysisEvents(placement.map((p, i) => event({ id: `e${i}`, instrument: "kick", ...p })));

      expect(totalSixteenths(score.measures[0])).toBe(16);
    }
  });

  it("should produce one measure per distinct measure number, filling any gaps", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", measure: 2, beat: 1, subdivision: 0 })]);

    expect(score.measures).toHaveLength(2);
    expect(score.measures[0][0].type).toBe("rest");
    expect(score.measures[1][0].type).toBe("note");
  });

  it("should ignore events missing measure, beat, or subdivision", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", measure: null })]);

    expect(score.measures).toEqual([]);
  });

  it("should carry each hit's original source time through unmodified", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 12.34 }),
      event({ id: "b", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 12.36 }),
    ]);

    const note = score.measures[0][0] as { type: string; hits: { time: number | null }[] };
    expect(note.hits.map((hit) => hit.time)).toEqual([12.34, 12.36]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- lib/score/__tests__/buildScore.test.ts`
Expected: FAIL — `Cannot find module '../buildScore'`

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/score/buildScore.ts
import type { AnalysisEvent } from "@/lib/api/jobs";
import { BEATS_PER_MEASURE, consolidateRests, SLOT_DURATION, SUBDIVISIONS_PER_BEAT } from "./grid";
import { generateId } from "./id";
import type { Measure, MusicalPosition, Score, ScoreNote, Slot } from "./types";

export function fromAnalysisEvents(events: AnalysisEvent[]): Score {
  const placeable = events.filter(
    (event): event is AnalysisEvent & { measure: number; beat: number; subdivision: number } =>
      event.measure != null && event.beat != null && event.subdivision != null,
  );

  if (placeable.length === 0) {
    return { measures: [] };
  }

  const grouped = new Map<string, AnalysisEvent[]>();
  for (const event of placeable) {
    const key = `${event.measure}:${event.beat}:${event.subdivision}`;
    const slotEvents = grouped.get(key);
    if (slotEvents) {
      slotEvents.push(event);
    } else {
      grouped.set(key, [event]);
    }
  }

  const maxMeasure = Math.max(...placeable.map((event) => event.measure));

  const measures: Measure[] = [];
  for (let measure = 1; measure <= maxMeasure; measure++) {
    const slots: Slot[] = [];

    for (let beat = 1; beat <= BEATS_PER_MEASURE; beat++) {
      for (let subdivision = 0; subdivision < SUBDIVISIONS_PER_BEAT; subdivision++) {
        const position: MusicalPosition = { measure, beat, subdivision };
        const slotEvents = grouped.get(`${measure}:${beat}:${subdivision}`);
        slots.push(
          slotEvents
            ? buildScoreNote(slotEvents, position)
            : { type: "rest", id: generateId("rest"), duration: SLOT_DURATION, position },
        );
      }
    }

    measures.push(consolidateRests(slots));
  }

  return { measures };
}

function buildScoreNote(slotEvents: AnalysisEvent[], position: MusicalPosition): ScoreNote {
  return {
    type: "note",
    id: generateId("note"),
    position,
    duration: SLOT_DURATION,
    hits: slotEvents.map((event) => ({
      id: generateId("hit"),
      sourceEventId: event.id,
      time: event.time,
      instrument: event.instrument,
      confidence: event.confidence,
      provenance: event.provenance ?? "unknown",
    })),
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- lib/score/__tests__/buildScore.test.ts`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/buildScore.ts frontend/lib/score/__tests__/buildScore.test.ts
git commit -m "feat: build the score domain model from AnalysisEvents"
```

---

### Task 6: Score transformations

**Files:**
- Create: `frontend/lib/score/transformations.ts`
- Test: `frontend/lib/score/__tests__/transformations.test.ts`

**Interfaces:**
- Consumes: `consolidateRests`, `expandMeasure`, `toSixteenthIndex`, `SLOT_DURATION` (Task 4); `generateId` (Task 1); `Measure`, `MusicalPosition`, `Score`, `ScoreHit`, `ScoreNote`, `Slot` (Task 3); `DrumInstrument` (`@/lib/api/jobs`); `fromAnalysisEvents` (Task 5, test-only, to build realistic fixtures).
- Produces: `addHit(score: Score, position: MusicalPosition, instrument: DrumInstrument): Score`, `deleteHit(score: Score, hitId: string): Score`, `moveHit(score: Score, hitId: string, newPosition: MusicalPosition): Score`, `changeInstrument(score: Score, hitId: string, newInstrument: DrumInstrument): Score` — consumed by Task 7's serialization round-trip test and, from Epic 5 onward, the correction editor UI (not built in this issue).

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/score/__tests__/transformations.test.ts
import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "../buildScore";
import { addHit, changeInstrument, deleteHit, moveHit } from "../transformations";
import type { Score, ScoreHit } from "../types";

function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    measure: 1,
    beat: 1,
    subdivision: 0,
    ...overrides,
  };
}

function hitsAt(score: Score, measure: number, beat: number, subdivision: number): ScoreHit[] {
  const slot = score.measures[measure - 1].find(
    (s) => s.position.beat === beat && s.position.subdivision === subdivision,
  );
  return slot?.type === "note" ? slot.hits : [];
}

describe("addHit", () => {
  it("should add a manually-added hit at an empty position", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", beat: 1, subdivision: 0 })]);

    const updated = addHit(score, { measure: 1, beat: 2, subdivision: 0 }, "snare");

    const hits = hitsAt(updated, 1, 2, 0);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ instrument: "snare", sourceEventId: null, time: null, provenance: "manual" });
  });

  it("should join an existing note as a second simultaneous hit", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", beat: 1, subdivision: 0 })]);

    const updated = addHit(score, { measure: 1, beat: 1, subdivision: 0 }, "hihat_closed");

    const hits = hitsAt(updated, 1, 1, 0);
    expect(hits.map((hit) => hit.instrument)).toEqual(["kick", "hihat_closed"]);
  });
});

describe("deleteHit", () => {
  it("should turn a single-hit note back into a rest", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", beat: 1, subdivision: 0 })]);
    const hitId = hitsAt(score, 1, 1, 0)[0].id;

    const updated = deleteHit(score, hitId);

    const slot = updated.measures[0].find((s) => s.position.beat === 1 && s.position.subdivision === 0);
    expect(slot?.type).toBe("rest");
  });

  it("should leave the remaining hit behind when deleting one of two simultaneous hits", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "snare", beat: 1, subdivision: 0 }),
    ]);
    const kickHitId = hitsAt(score, 1, 1, 0).find((hit) => hit.instrument === "kick")!.id;

    const updated = deleteHit(score, kickHitId);

    expect(hitsAt(updated, 1, 1, 0).map((hit) => hit.instrument)).toEqual(["snare"]);
  });
});

describe("moveHit", () => {
  it("should relocate a hit to a new position while preserving its id, source link, and time", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 1.5 }),
    ]);
    const original = hitsAt(score, 1, 1, 0)[0];

    const updated = moveHit(score, original.id, { measure: 1, beat: 3, subdivision: 0 });

    expect(hitsAt(updated, 1, 1, 0)).toHaveLength(0);
    expect(hitsAt(updated, 1, 3, 0)[0]).toEqual(original);
  });
});

describe("changeInstrument", () => {
  it("should update a hit's instrument without changing its position or source link", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 0.5 }),
    ]);
    const original = hitsAt(score, 1, 1, 0)[0];

    const updated = changeInstrument(score, original.id, "tom_low");

    expect(hitsAt(updated, 1, 1, 0)[0]).toEqual({ ...original, instrument: "tom_low" });
  });
});

describe("source link preservation", () => {
  it("should leave every other hit's id, sourceEventId, and time unchanged when one hit is edited", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
      event({ id: "b", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
    ]);
    const untouched = hitsAt(score, 1, 2, 0)[0];
    const targetId = hitsAt(score, 1, 1, 0)[0].id;

    const updated = changeInstrument(score, targetId, "tom_low");

    expect(hitsAt(updated, 1, 2, 0)[0]).toEqual(untouched);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- lib/score/__tests__/transformations.test.ts`
Expected: FAIL — `Cannot find module '../transformations'`

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/score/transformations.ts
import type { DrumInstrument } from "@/lib/api/jobs";
import { consolidateRests, expandMeasure, SLOT_DURATION, toSixteenthIndex } from "./grid";
import { generateId } from "./id";
import type { MusicalPosition, Score, ScoreHit, ScoreNote, Slot } from "./types";

export function addHit(score: Score, position: MusicalPosition, instrument: DrumInstrument): Score {
  const hit: ScoreHit = {
    id: generateId("hit"),
    sourceEventId: null,
    time: null,
    instrument,
    confidence: null,
    provenance: "manual",
  };

  return insertHit(score, position, hit);
}

export function deleteHit(score: Score, hitId: string): Score {
  const measures = score.measures.map((measure, index) => {
    const measureNumber = index + 1;
    const containsHit = measure.some((slot) => slot.type === "note" && slot.hits.some((hit) => hit.id === hitId));
    if (!containsHit) {
      return measure;
    }

    const expanded = expandMeasure(measure, measureNumber);
    const updated = expanded.map((slot): Slot => {
      if (slot.type !== "note") {
        return slot;
      }
      const hits = slot.hits.filter((hit) => hit.id !== hitId);
      if (hits.length === 0) {
        return { type: "rest", id: generateId("rest"), duration: SLOT_DURATION, position: slot.position };
      }
      return { ...slot, hits };
    });

    return consolidateRests(updated);
  });

  return { measures };
}

export function moveHit(score: Score, hitId: string, newPosition: MusicalPosition): Score {
  const hit = findHit(score, hitId);
  if (!hit) {
    return score;
  }

  return insertHit(deleteHit(score, hitId), newPosition, hit);
}

export function changeInstrument(score: Score, hitId: string, newInstrument: DrumInstrument): Score {
  const measures = score.measures.map((measure) =>
    measure.map((slot): Slot => {
      if (slot.type !== "note") {
        return slot;
      }
      return {
        ...slot,
        hits: slot.hits.map((hit) => (hit.id === hitId ? { ...hit, instrument: newInstrument } : hit)),
      };
    }),
  );

  return { measures };
}

function insertHit(score: Score, position: MusicalPosition, hit: ScoreHit): Score {
  const measures = score.measures.map((measure, index) => {
    const measureNumber = index + 1;
    if (measureNumber !== position.measure) {
      return measure;
    }

    const expanded = expandMeasure(measure, measureNumber);
    const sixteenthIndex = toSixteenthIndex(position);
    const existing = expanded[sixteenthIndex];
    const note: ScoreNote =
      existing.type === "note"
        ? { ...existing, hits: [...existing.hits, hit] }
        : { type: "note", id: generateId("note"), position, duration: SLOT_DURATION, hits: [hit] };

    expanded[sixteenthIndex] = note;

    return consolidateRests(expanded);
  });

  return { measures };
}

function findHit(score: Score, hitId: string): ScoreHit | undefined {
  for (const measure of score.measures) {
    for (const slot of measure) {
      if (slot.type === "note") {
        const hit = slot.hits.find((h) => h.id === hitId);
        if (hit) {
          return hit;
        }
      }
    }
  }
  return undefined;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- lib/score/__tests__/transformations.test.ts`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/transformations.ts frontend/lib/score/__tests__/transformations.test.ts
git commit -m "feat: add score domain model transformations"
```

---

### Task 7: Score serialization

**Files:**
- Create: `frontend/lib/score/serialization.ts`
- Test: `frontend/lib/score/__tests__/serialization.test.ts`

**Interfaces:**
- Consumes: `Score` (Task 3); `fromAnalysisEvents` (Task 5, test-only); `addHit` (Task 6, test-only).
- Produces: `toJSON(score: Score): unknown`, `fromJSON(json: unknown): Score` — not consumed elsewhere in this issue; documented boundary for future persistence (Epic 6).

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/score/__tests__/serialization.test.ts
import { fromAnalysisEvents } from "../buildScore";
import { fromJSON, toJSON } from "../serialization";
import { addHit } from "../transformations";

describe("toJSON / fromJSON", () => {
  it("should round-trip a freshly constructed score", () => {
    const score = fromAnalysisEvents([
      {
        id: "e",
        time: 0.5,
        instrument: "kick",
        confidence: 0.9,
        provenance: "drumscript",
        measure: 1,
        beat: 1,
        subdivision: 0,
      },
    ]);

    const roundTripped = fromJSON(toJSON(score));

    expect(roundTripped).toEqual(score);
  });

  it("should round-trip a score that has been through a transformation", () => {
    const score = fromAnalysisEvents([
      {
        id: "e",
        time: 0.5,
        instrument: "kick",
        confidence: 0.9,
        provenance: "drumscript",
        measure: 1,
        beat: 1,
        subdivision: 0,
      },
    ]);
    const edited = addHit(score, { measure: 1, beat: 2, subdivision: 0 }, "snare");

    const roundTripped = fromJSON(toJSON(edited));

    expect(roundTripped).toEqual(edited);
  });

  it("should reject JSON that has no measures array", () => {
    expect(() => fromJSON({})).toThrow("Invalid score JSON");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- lib/score/__tests__/serialization.test.ts`
Expected: FAIL — `Cannot find module '../serialization'`

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/score/serialization.ts
import type { Score } from "./types";

export function toJSON(score: Score): unknown {
  return JSON.parse(JSON.stringify(score));
}

export function fromJSON(json: unknown): Score {
  if (typeof json !== "object" || json === null || !Array.isArray((json as { measures?: unknown }).measures)) {
    throw new Error("Invalid score JSON: expected an object with a measures array");
  }
  return json as Score;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- lib/score/__tests__/serialization.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/score/serialization.ts frontend/lib/score/__tests__/serialization.test.ts
git commit -m "feat: add score domain model JSON serialization"
```

---

### Task 8: Repoint buildStaveNote at the domain model

**Files:**
- Modify: `frontend/lib/notation/buildStaveNote.ts`
- Modify: `frontend/lib/notation/__tests__/buildStaveNote.test.ts`

**Interfaces:**
- Consumes: `Slot`, `ScoreHit` (Task 3, `@/lib/score/types`); `INSTRUMENT_NOTATION` (existing, `./instrumentNotation`).
- Produces: `buildStaveNote(slot: Slot): StaveNote` (signature unchanged from today's `buildStaveNote(slot: SlotSpec)`, so `DrumScore.tsx`'s call site in Task 9 doesn't need to change how it's invoked).

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `frontend/lib/notation/__tests__/buildStaveNote.test.ts`:

```ts
// frontend/lib/notation/__tests__/buildStaveNote.test.ts
import { Stem } from "vexflow";

import type { ScoreHit } from "@/lib/score/types";
import { buildStaveNote } from "../buildStaveNote";

function hit(overrides: Partial<ScoreHit>): ScoreHit {
  return {
    id: "h",
    sourceEventId: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    ...overrides,
  };
}

describe("buildStaveNote", () => {
  it("should force an upward stem for a kick-only note", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "kick" })],
    });

    expect(note.getStemDirection()).toBe(Stem.UP);
  });

  it("should force an upward stem for a snare-only note", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "snare" })],
    });

    expect(note.getStemDirection()).toBe(Stem.UP);
  });

  it("should force an upward stem even for a kick+snare+hihat chord", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [
        hit({ id: "h1", instrument: "kick" }),
        hit({ id: "h2", instrument: "snare" }),
        hit({ id: "h3", instrument: "hihat_closed" }),
      ],
    });

    expect(note.getStemDirection()).toBe(Stem.UP);
    expect(note.getKeys()).toEqual(["f/4", "c/5", "g/5/x2"]);
  });

  it("should build a rest for a rest slot", () => {
    const note = buildStaveNote({
      type: "rest",
      id: "r",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
    });

    expect(note.isRest()).toBe(true);
  });

  it("should attach an articulation for an open hi-hat", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "hihat_open" })],
    });

    expect(note.getModifiersByType("Articulation")).toHaveLength(1);
  });

  it("should deduplicate identical instruments among simultaneous hits", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ id: "h1", instrument: "kick" }), hit({ id: "h2", instrument: "kick" })],
    });

    expect(note.getKeys()).toEqual(["f/4"]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- buildStaveNote.test.ts`
Expected: FAIL — `buildStaveNote` is called with a `Slot`-shaped object but the current implementation reads `slot.keys`/`slot.articulations`, which no longer exist, so most assertions fail (empty keys, no articulations, etc).

- [ ] **Step 3: Write the minimal implementation**

Replace the full contents of `frontend/lib/notation/buildStaveNote.ts`:

```ts
// frontend/lib/notation/buildStaveNote.ts
import { Articulation, StaveNote } from "vexflow";

import type { Slot } from "@/lib/score/types";
import { INSTRUMENT_NOTATION } from "./instrumentNotation";

export function buildStaveNote(slot: Slot): StaveNote {
  if (slot.type === "rest") {
    return new StaveNote({ keys: ["b/4"], duration: `${slot.duration}r` });
  }

  const instruments = Array.from(new Set(slot.hits.map((hit) => hit.instrument)));

  const note = new StaveNote({
    keys: instruments.map((instrument) => INSTRUMENT_NOTATION[instrument].key),
    duration: slot.duration,
    stemDirection: 1,
    autoStem: false,
  });

  instruments
    .map((instrument) => INSTRUMENT_NOTATION[instrument].articulation)
    .filter((articulation): articulation is string => Boolean(articulation))
    .forEach((articulation) => {
      note.addModifier(new Articulation(articulation));
    });

  return note;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- buildStaveNote.test.ts`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/notation/buildStaveNote.ts frontend/lib/notation/__tests__/buildStaveNote.test.ts
git commit -m "feat: repoint buildStaveNote at the score domain model"
```

---

### Task 9: Repoint DrumScore at the domain model and delete the old buildScore

`buildStaveNote.ts` (Task 8) is already repointed, so once `DrumScore.tsx` stops importing the old `lib/notation/buildScore.ts`, nothing references it and it can be deleted along with its test. This task is a same-behavior integration swap, verified by the existing `DrumScore.test.tsx`/`EndToEndFlow.test.tsx` suites staying green rather than by new tests (no new behavior is introduced).

**Files:**
- Modify: `frontend/components/DrumScore.tsx`
- Delete: `frontend/lib/notation/buildScore.ts`
- Delete: `frontend/lib/notation/__tests__/buildScore.test.ts`

**Interfaces:**
- Consumes: `fromAnalysisEvents` (Task 5, `@/lib/score/buildScore`).

- [ ] **Step 1: Repoint the import and the two usages**

In `frontend/components/DrumScore.tsx`, change:

```tsx
import { buildMeasures } from "@/lib/notation/buildScore";
```

to:

```tsx
import { fromAnalysisEvents } from "@/lib/score/buildScore";
```

Change:

```tsx
    const measures = buildMeasures(events);
    if (measures.length === 0) {
```

to:

```tsx
    const { measures } = fromAnalysisEvents(events);
    if (measures.length === 0) {
```

Change the playhead-timeline block inside the `measures.forEach` callback from:

```tsx
      notes.forEach((note, slotIndex) => {
        const slot = measure[slotIndex];
        // Only note slots are anchored to a real source timestamp - rest
        // slots have no underlying event, so the playhead interpolates
        // smoothly across them between the nearest real anchors instead of
        // reconstructing a time from a BPM/grid assumption (see
        // interpolatePlayheadX in lib/notation/timeline.ts).
        if (slot.type !== "note") {
          return;
        }
        timelineRef.current.push({
          time: averageSourceTime(slot.sourceTimes),
          x: note.getAbsoluteX(),
          row,
        });
      });
```

to:

```tsx
      notes.forEach((note, slotIndex) => {
        const slot = measure[slotIndex];
        // Only note slots are anchored to a real source timestamp - rest
        // slots have no underlying event, so the playhead interpolates
        // smoothly across them between the nearest real anchors instead of
        // reconstructing a time from a BPM/grid assumption (see
        // interpolatePlayheadX in lib/notation/timeline.ts).
        if (slot.type !== "note") {
          return;
        }
        const times = slot.hits.map((hit) => hit.time).filter((time): time is number => time != null);
        if (times.length === 0) {
          return;
        }
        timelineRef.current.push({
          time: averageSourceTime(times),
          x: note.getAbsoluteX(),
          row,
        });
      });
```

- [ ] **Step 2: Run the DrumScore and end-to-end suites to verify the swap is behavior-preserving**

Run: `npm test -- DrumScore.test.tsx EndToEndFlow.test.tsx`
Expected: PASS — same test count and assertions as before this task, unchanged, since the rendered VexFlow output for the same input events is identical.

- [ ] **Step 3: Delete the superseded module and its test**

```bash
git rm frontend/lib/notation/buildScore.ts frontend/lib/notation/__tests__/buildScore.test.ts
```

- [ ] **Step 4: Run the full frontend suite, lint, and typecheck**

Run: `npm test && npm run lint && npx tsc --noEmit` (from `frontend/`)
Expected: PASS — full suite green, no lint errors, no type errors. This also confirms nothing else in the tree still imports the deleted module (grep for `notation/buildScore` should return nothing).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/DrumScore.tsx
git commit -m "feat: repoint DrumScore at the score domain model, delete legacy buildScore"
```

---

## Self-Review Notes

**Spec coverage:** every spec section has a task — data model (Task 3), construction (Task 5), transformations (Task 6), serialization (Task 7), integration changes (Tasks 8-9), confidence/provenance threading (Task 2), file layout (Tasks 1-7 match the spec's file list exactly), non-goals (no task touches duration consolidation, beaming, hi-hat notation, layout, or golden tests — confirmed by grep showing only `DrumScore.tsx`/`buildStaveNote.ts`/the two old-`buildScore` files reference the code being replaced).

**Type consistency:** `Slot`/`ScoreNote`/`ScoreRest`/`ScoreHit`/`Measure`/`Score`/`MusicalPosition` (Task 3) are used with identical field names across every later task. `fromAnalysisEvents` (Task 5), `addHit`/`deleteHit`/`moveHit`/`changeInstrument` (Task 6), `toJSON`/`fromJSON` (Task 7), and `buildStaveNote` (Task 8) signatures match what each consuming task expects.
