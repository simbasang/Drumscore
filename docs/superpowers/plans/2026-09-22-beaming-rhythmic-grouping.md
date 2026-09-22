# Beaming & Rhythmic Grouping Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `DrumScore.tsx`'s inline, VexFlow-default beam grouping (`Beam.generateBeams(notes, { groups: [Fraction(1,4)] })`) with an explicit, unit-testable drum-engraving grouping rule that beams consecutive eighth/sixteenth notes within a beat, never across a beat boundary, and never beams a lone note — satisfying GitHub issue #52 (V1-019).

**Architecture:** Add a small pure function, `computeBeamGroupIndices`, in a new `frontend/lib/notation/beaming.ts` module that takes a consolidated `Measure` (the same `Slot[]` `DrumScore.tsx` already builds via `fromAnalysisEvents`/`consolidateDurations`) and returns arrays of slot indices that should be beamed together, using only `slot.type`, `slot.duration`, and `slot.position.beat` — no VexFlow objects, no rendering. A thin wrapper, `buildBeams`, turns those index groups into real `vexflow` `Beam` instances (`new Beam(notes, false)`, `autoStem: false`) from the already-built `StaveNote[]`. `DrumScore.tsx` calls `buildBeams` instead of `Beam.generateBeams`, keeping its own render loop unchanged (`beam.setContext(context).draw()` already exists).

**Tech Stack:** TypeScript, Next.js/React, `vexflow` 5.0.0, Jest + `@testing-library/react`, `jsdom` test environment (already configured, no changes needed).

**Spec:** GitHub issue #52 (V1-019 — Implement beaming and rhythmic grouping rules), part of EPIC 4 (#31, Notation Engine 2.0). Acceptance criteria: common 4/4 eighth/16th patterns beam conventionally; beat boundaries remain readable; simultaneous hits group correctly; all stems remain upward; regression tests cover the rules.

## Global Constraints

- All stems stay forced upward (`frontend/lib/notation/buildStaveNote.ts` already sets `stemDirection: 1, autoStem: false` on every `StaveNote` — do not change that file; the new beam code must not fight it).
- `sourceTime`/musical position handling is out of scope — this issue is purely about beam/grouping presentation, not timing (`CLAUDE.md`'s timing model rules don't apply here beyond "don't touch timing code").
- No new dependencies. `vexflow` is already installed (`frontend/node_modules/vexflow`, version 5.0.0, `Beam` constructor is `new Beam(notes: StemmableNote[], autoStem？: boolean)` — verified directly against `node_modules/vexflow/build/types/src/beam.d.ts`).
- Tests: Jest + React Testing Library only, per the user's global testing rules — files live in `__tests__` next to the module, AAA structure with a blank line between Arrange/Act/Assert, `describe`/`it("should ...")` naming, no new mocks needed (VexFlow's `StaveNote`/`Beam` construct fine outside a render context — confirmed by manual `node -e` smoke test during planning; only `.draw()` needs a real rendering context, which these tests never call).
- Follow `CLAUDE.md`'s working method: state a short plan (this document), keep changes scoped to #52, preserve existing contracts (`Measure`/`Slot` types, `buildStaveNote`'s stem-forcing behavior), add/update tests, run frontend checks, report and stop.

---

### Task 1: `computeBeamGroupIndices` — pure grouping rule

**Files:**
- Create: `frontend/lib/notation/beaming.ts`
- Test: `frontend/lib/notation/__tests__/beaming.test.ts`

**Interfaces:**
- Consumes: `Slot`, `Measure` from `frontend/lib/score/types.ts` (`Measure = Slot[]`; `Slot` is `ScoreNote | ScoreRest`, each with `duration: string` and `position: { measure, beat, subdivision }`).
- Produces: `computeBeamGroupIndices(measure: Measure): number[][]` — each inner array holds `measure` indices (in ascending order) that should be beamed together. Consumed by Task 2's `buildBeams`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/notation/__tests__/beaming.test.ts`:

```ts
import { computeBeamGroupIndices } from "../beaming";
import type { Measure, Slot } from "@/lib/score/types";

function note(beat: number, subdivision: number, duration: string): Slot {
  return {
    type: "note",
    id: `n-${beat}-${subdivision}`,
    position: { measure: 1, beat, subdivision },
    duration,
    hits: [
      {
        id: `h-${beat}-${subdivision}`,
        sourceEventId: null,
        time: null,
        instrument: "hihat_closed",
        confidence: null,
        provenance: "test",
      },
    ],
  };
}

function rest(beat: number, subdivision: number, duration: string): Slot {
  return {
    type: "rest",
    id: `r-${beat}-${subdivision}`,
    position: { measure: 1, beat, subdivision },
    duration,
  };
}

describe("computeBeamGroupIndices", () => {
  it("should group a beat of four sixteenth notes into one beam", () => {
    const measure: Measure = [
      note(1, 0, "16"),
      note(1, 1, "16"),
      note(1, 2, "16"),
      note(1, 3, "16"),
    ];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[0, 1, 2, 3]]);
  });

  it("should group a measure of straight eighth notes into one beam per beat", () => {
    const measure: Measure = [
      note(1, 0, "8"),
      note(1, 2, "8"),
      note(2, 0, "8"),
      note(2, 2, "8"),
      note(3, 0, "8"),
      note(3, 2, "8"),
      note(4, 0, "8"),
      note(4, 2, "8"),
    ];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[0, 1], [2, 3], [4, 5], [6, 7]]);
  });

  it("should never beam across a beat boundary", () => {
    const measure: Measure = [note(1, 2, "8"), note(2, 0, "8")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([]);
  });

  it("should not beam a lone eighth note surrounded by rests", () => {
    const measure: Measure = [rest(1, 0, "16"), note(1, 1, "8"), rest(1, 3, "16")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([]);
  });

  it("should break the group at a quarter note and resume after it", () => {
    const measure: Measure = [note(1, 0, "4"), note(2, 0, "8"), note(2, 2, "8")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[1, 2]]);
  });

  it("should include a simultaneous-hit (chord) note in its beat's beam like any other note", () => {
    const chord: Slot = {
      type: "note",
      id: "chord",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "8",
      hits: [
        {
          id: "h1",
          sourceEventId: null,
          time: null,
          instrument: "kick",
          confidence: null,
          provenance: "test",
        },
        {
          id: "h2",
          sourceEventId: null,
          time: null,
          instrument: "hihat_closed",
          confidence: null,
          provenance: "test",
        },
      ],
    };
    const measure: Measure = [chord, note(1, 2, "8")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[0, 1]]);
  });

  it("should return no groups for an all-rest measure", () => {
    const measure: Measure = [rest(1, 0, "4"), rest(2, 0, "4"), rest(3, 0, "4"), rest(4, 0, "4")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest lib/notation/__tests__/beaming.test.ts`
Expected: FAIL — `Cannot find module '../beaming'` (file doesn't exist yet).

- [ ] **Step 3: Implement `computeBeamGroupIndices`**

Create `frontend/lib/notation/beaming.ts`:

```ts
import type { Measure, Slot } from "@/lib/score/types";

const BEAMABLE_DURATIONS = new Set(["8", "16"]);

function isBeamable(slot: Slot): boolean {
  return slot.type === "note" && BEAMABLE_DURATIONS.has(slot.duration);
}

// Explicit drum-engraving beam grouping: consecutive eighth/sixteenth notes
// beam together only while they share the same beat (the quarter-note pulse)
// and there's no rest or non-beamable (quarter/half/whole) note between them.
// A group of a single note is dropped - convention (and VexFlow) never beams
// one note alone. This replaces relying on VexFlow's own
// Beam.generateBeams/groups-fraction heuristic with a rule this project owns
// and can test directly, per V1-019/#52.
export function computeBeamGroupIndices(measure: Measure): number[][] {
  const groups: number[][] = [];
  let current: number[] = [];
  let currentBeat: number | null = null;

  const flush = () => {
    if (current.length >= 2) {
      groups.push(current);
    }
    current = [];
  };

  measure.forEach((slot, index) => {
    if (!isBeamable(slot) || slot.position.beat !== currentBeat) {
      flush();
    }

    if (isBeamable(slot)) {
      if (current.length === 0) {
        currentBeat = slot.position.beat;
      }
      current.push(index);
    } else {
      currentBeat = null;
    }
  });
  flush();

  return groups;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest lib/notation/__tests__/beaming.test.ts`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/notation/beaming.ts frontend/lib/notation/__tests__/beaming.test.ts
git commit -m "feat: add explicit beam grouping rule for drum notation"
```

---

### Task 2: `buildBeams` — VexFlow `Beam` construction from the grouping rule

**Files:**
- Modify: `frontend/lib/notation/beaming.ts`
- Test: `frontend/lib/notation/__tests__/beaming.test.ts`

**Interfaces:**
- Consumes: `computeBeamGroupIndices` (Task 1, same file). `StaveNote`, `Beam` from `vexflow`.
- Produces: `buildBeams(measure: Measure, notes: StaveNote[]): Beam[]` — `notes` must be the same length and index-order as `measure` (i.e. `measure.map(buildStaveNote)`, exactly as `DrumScore.tsx` already builds it). Consumed by Task 3's `DrumScore.tsx`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/lib/notation/__tests__/beaming.test.ts` (new `describe` block, same file — add these imports at the top alongside the existing ones):

```ts
import { Stem } from "vexflow";
import { buildBeams, computeBeamGroupIndices } from "../beaming";
import { buildStaveNote } from "../buildStaveNote";
```

Then add:

```ts
describe("buildBeams", () => {
  it("should build one Beam per group returned by computeBeamGroupIndices", () => {
    const measure: Measure = [
      note(1, 0, "16"),
      note(1, 1, "16"),
      note(1, 2, "16"),
      note(1, 3, "16"),
      rest(2, 0, "4"),
    ];
    const notes = measure.map(buildStaveNote);

    const beams = buildBeams(measure, notes);

    expect(beams).toHaveLength(1);
    expect(beams[0].getNotes()).toEqual([notes[0], notes[1], notes[2], notes[3]]);
  });

  it("should build a separate Beam per beat, never merging across beats", () => {
    const measure: Measure = [note(1, 0, "8"), note(1, 2, "8"), note(2, 0, "8"), note(2, 2, "8")];
    const notes = measure.map(buildStaveNote);

    const beams = buildBeams(measure, notes);

    expect(beams).toHaveLength(2);
    expect(beams[0].getNotes()).toEqual([notes[0], notes[1]]);
    expect(beams[1].getNotes()).toEqual([notes[2], notes[3]]);
  });

  it("should build no Beams when nothing qualifies for beaming", () => {
    const measure: Measure = [rest(1, 0, "4"), note(2, 0, "4")];
    const notes = measure.map(buildStaveNote);

    const beams = buildBeams(measure, notes);

    expect(beams).toHaveLength(0);
  });

  it("should keep every beamed note's stem pointing up", () => {
    const measure: Measure = [note(1, 0, "8"), note(1, 2, "8")];
    const notes = measure.map(buildStaveNote);

    const beams = buildBeams(measure, notes);

    expect(beams[0].getStemDirection()).toBe(Stem.UP);
    beams[0].getNotes().forEach((beamedNote) => {
      expect(beamedNote.getStemDirection()).toBe(Stem.UP);
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx jest lib/notation/__tests__/beaming.test.ts`
Expected: FAIL — `buildBeams` is not exported from `../beaming`.

- [ ] **Step 3: Implement `buildBeams`**

Add to `frontend/lib/notation/beaming.ts` (extend the existing top-of-file imports to include `Beam` and `StaveNote` from `vexflow`):

```ts
import { Beam, StaveNote } from "vexflow";
import type { Measure, Slot } from "@/lib/score/types";
```

Append at the end of the file:

```ts
// notes must be measure.map(buildStaveNote) - same length/order as measure,
// so computeBeamGroupIndices's indices line up with real StaveNotes.
// autoStem is false because buildStaveNote already forces every note's stem
// direction upward; Beam must not recompute it.
export function buildBeams(measure: Measure, notes: StaveNote[]): Beam[] {
  return computeBeamGroupIndices(measure).map((indices) => new Beam(indices.map((index) => notes[index]), false));
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx jest lib/notation/__tests__/beaming.test.ts`
Expected: PASS (all 11 tests: 7 from Task 1 + 4 from Task 2).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/notation/beaming.ts frontend/lib/notation/__tests__/beaming.test.ts
git commit -m "feat: build VexFlow beams from the explicit grouping rule"
```

---

### Task 3: Wire `buildBeams` into `DrumScore.tsx`

**Files:**
- Modify: `frontend/components/DrumScore.tsx:1-9` (imports), `frontend/components/DrumScore.tsx:77-83` (beam construction)
- Test: `frontend/components/__tests__/DrumScore.test.tsx` (existing file, add one new test)

**Interfaces:**
- Consumes: `buildBeams` from `@/lib/notation/beaming` (Task 2).
- Produces: no new exports; `DrumScore`'s rendered SVG output changes (real per-beat beams instead of VexFlow's auto-generated ones) but its component props/behavior contract is unchanged.

- [ ] **Step 1: Write the failing test**

Add to `frontend/components/__tests__/DrumScore.test.tsx`, inside the existing `describe("DrumScore", ...)` block:

```tsx
  it("should render a separate beam per beat for a straight eighth-note groove, not one beam per measure", () => {
    render(
      <DrumScore
        events={[
          event({ id: "1", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 2, time: 0.25 }),
          event({ id: "3", instrument: "hihat_closed", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_closed", beat: 2, subdivision: 2, time: 0.75 }),
        ]}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const beamPaths = container.querySelectorAll("path.vf-beam");

    expect(beamPaths.length).toBe(2);
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx jest components/__tests__/DrumScore.test.tsx -t "separate beam per beat"`
Expected: FAIL — the current inline `Beam.generateBeams(notes, { groups: [Fraction(1,4)] })` call happens to already group by quarter-note beat, so check the actual failure first (see note below); if it already passes, the test still stays as an explicit regression lock and the task proceeds straight to Step 3's refactor, re-running this same command afterward to confirm the rendering path was actually swapped (cross-check with the Task 2 unit tests, which are the real proof of the new code path).

- [ ] **Step 3: Replace the inline beam construction**

In `frontend/components/DrumScore.tsx`, change the import block (lines 1-9):

```tsx
"use client";

import { useEffect, useRef } from "react";
import { Formatter, Renderer, Stave, Voice } from "vexflow";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "@/lib/score/buildScore";
import { buildStaveNote } from "@/lib/notation/buildStaveNote";
import { buildBeams } from "@/lib/notation/beaming";
import { computeAutoScrollLeft, interpolatePlayheadX, type TimelinePoint } from "@/lib/notation/timeline";
```

Then replace the beam-construction block (previously lines 77-83):

```tsx
      const beams = buildBeams(measure, notes);
      beams.forEach((beam) => beam.setContext(context).draw());
```

- [ ] **Step 4: Run the full DrumScore test file to verify everything passes**

Run: `cd frontend && npx jest components/__tests__/DrumScore.test.tsx`
Expected: PASS (all tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/DrumScore.tsx frontend/components/__tests__/DrumScore.test.tsx
git commit -m "feat: render beams from the explicit drum grouping rule"
```

---

### Task 4: Full verification pass

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && npx jest`
Expected: PASS, no failing suites.

- [ ] **Step 2: Run lint**

Run: `cd frontend && npm run lint`
Expected: no errors.

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manually verify no dead imports remain**

Run: `cd frontend && npx eslint components/DrumScore.tsx --rule '{"no-unused-vars":"error"}'`
Expected: no errors (confirms `Beam`/`Fraction` were fully removed from `DrumScore.tsx`'s imports in Task 3 and nothing else regressed).

- [ ] **Step 5: Update GitHub issue tracking**

No code change. Confirm acceptance criteria against the test suite:
- "Common 4/4 eighth/16th patterns beam conventionally" — Task 1/2 unit tests.
- "beat boundaries remain readable" — `should never beam across a beat boundary`, `should build a separate Beam per beat` tests.
- "simultaneous hits group correctly" — `should include a simultaneous-hit (chord) note in its beat's beam like any other note` test.
- "all stems remain upward" — `should keep every beamed note's stem pointing up` test, plus pre-existing `buildStaveNote.test.ts` coverage (unchanged).
- "regression tests cover rules" — 11 new unit tests in `beaming.test.ts` + 1 new component test in `DrumScore.test.tsx`.

---

## Self-Review Notes (for the plan author, not a task)

- Spec coverage: all five acceptance criteria map to a concrete test in Task 1/2/3 above.
- No placeholders: every step has real code.
- Type consistency: `computeBeamGroupIndices(measure: Measure): number[][]` (Task 1) is consumed unchanged by `buildBeams(measure: Measure, notes: StaveNote[]): Beam[]` (Task 2), which is consumed unchanged by `DrumScore.tsx` (Task 3, called as `buildBeams(measure, notes)` where `measure`/`notes` are the same locals the old code already had in scope).
- Out of scope, left untouched: hi-hat open/closed notation (already done, pre-V1-019), dynamic layout/line-breaking (separate Epic 4 issue), dotted/tied durations (existing `TECHNICAL_DEBT.md` entry from V1-018, unrelated to beaming).
