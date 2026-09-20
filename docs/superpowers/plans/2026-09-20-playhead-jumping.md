# Playhead Jumping Root-Cause Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the reported playhead jumping by addressing its proven root cause, and add regression coverage that fails on the old behavior and passes on the fix.

**Root cause (Phase 1 investigation, completed before writing this plan):**

`DrumScore.tsx`'s render effect builds one `TimelinePoint` per rendered note/rest slot, iterating measures 1..N and, within each measure, slots in strictly increasing `(beat, subdivision)` order (`frontend/components/DrumScore.tsx:57-102`, `frontend/lib/notation/buildScore.ts:60-79`). Because every slot's `time` comes from `computeSlotTimeSeconds(measure, beat, subdivision, tempoBpm, ...)` — a pure function of grid position and a single constant BPM (`frontend/lib/notation/timeline.ts:10-22`) — `timelineRef.current` is *always* sorted by non-decreasing `time` by construction. That rules out the "unstable event reference" and "tempo drift" hypotheses as sources of backward motion: given a stable `events`/`tempoBpm` prop (true here — `Player.tsx` passes them straight through from its own props, unchanged by its own per-tick re-renders) and a single constant BPM, the timeline itself cannot go non-monotonic.

The actual bug is in `interpolatePlayheadX` (`frontend/lib/notation/timeline.ts:24-58`). Adjacent `TimelinePoint`s from *different rows* have unrelated x-coordinates — a new row restarts at the left margin (`x ≈ 10`) while the previous row's last slot sits at the right edge (`x ≈ 790`, given `MEASURES_PER_ROW = 4` and `MEASURE_WIDTH = 200`, `DrumScore.tsx:22-23`). The function does not special-case this: it linearly interpolates `x` between the two points regardless of row, and reports `row: a.row` (the *old* row) for every point in between. So as real playback time crosses a row boundary, the reported x **decreases** (slides from ~790 back toward ~10) while still being drawn on the old row's line — a visible backward jump — immediately followed by a hard cut down to the new row once `time` reaches the boundary point exactly. This reproduces reliably and deterministically for any multi-row score; it is not timing/environment dependent. Confirmed by reading the existing (pre-fix) test named `"should use the left point's row for interpolated positions"` in `frontend/lib/notation/__tests__/timeline.test.ts:50-57`, which encodes exactly this blend as intended behavior — proving it was a designed gap, not a flake.

Concrete numbers: points `{time: 0, x: 190, row: 0}` and `{time: 1, x: 10, row: 1}`. At `time = 0.5`, current code returns `{x: 100, row: 0}` — 90px to the *left* of where row 0's last real note (x=190) was drawn, one frame after the playhead was visibly at x=190. That backward slide, repeated at every row boundary throughout a song, is what "playhead jumps back and forth… especially visible across row breaks" (the informal report this issue tracks) describes.

**Fix:** When the two bracketing points belong to different rows, do not interpolate `x` across them — there is no meaningful "in-between" position between the end of one printed line and the start of the next. Instead, hold at the old row's last point until the new row's first point's time is reached, then cut directly to it. This is a one-function change with no new dependencies.

**Tech Stack:** TypeScript, Jest, React Testing Library (existing frontend stack — no new dependencies).

**Spec:** GitHub issue #36 (V1-003), part of EPIC 1 (#28). `docs/ARCHITECTURE_V1.md`'s Playback section: "The playhead asks timing/score mapping where source time belongs; it never accumulates BPM ticks" — satisfied already by `SyncedPlayer`/`Player.tsx` (verified during investigation, not touched by this fix). `PROJECT.md`'s non-negotiable rule 3: "Do not patch symptoms such as smoothing a playhead whose underlying timing model is wrong" — this plan fixes the actual interpolation logic, not a smoothing/debounce band-aid.

## Global Constraints

- Fix the proven root cause only (`interpolatePlayheadX`'s cross-row interpolation) — do not touch `SyncedPlayer`, `computeSlotTimeSeconds`, or the backend quantization pipeline; they were investigated and ruled out as sources of this specific bug.
- The playhead must move monotonically (in the sense of never sliding backward within a single row) except on an explicit seek/loop — verified by tests, not just visual inspection.
- No "while I'm here" changes: `computeAutoScrollLeft` and the rest of `DrumScore.tsx` are unrelated to this bug and stay as-is.
- Frontend tests follow this repo's Jest + React Testing Library convention (`frontend/CLAUDE.md`/global testing rules): AAA structure, `__tests__` folders beside the file under test.

---

### Task 1: Fix `interpolatePlayheadX` to stop blending x across a row change

**Files:**
- Modify: `frontend/lib/notation/timeline.ts`
- Test: `frontend/lib/notation/__tests__/timeline.test.ts`

**Interfaces:**
- Consumes/produces: `interpolatePlayheadX(points: TimelinePoint[], time: number): TimelinePoint | null` — signature unchanged, only its cross-row behavior changes.

- [ ] **Step 1: Replace the test that encodes the buggy blend, and add tests for the fixed behavior**

In `frontend/lib/notation/__tests__/timeline.test.ts`, replace this existing test:

```ts
  it("should use the left point's row for interpolated positions", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const result = interpolatePlayheadX(rowChangePoints, 0.5);
    expect(result?.row).toBe(0);
  });
```

with:

```ts
  it("should hold at the old row's last point instead of sliding backward into the next row's x", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const result = interpolatePlayheadX(rowChangePoints, 0.5);
    expect(result).toEqual({ time: 0.5, x: 190, row: 0 });
  });

  it("should cut directly to the new row's first point once its time is reached", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const result = interpolatePlayheadX(rowChangePoints, 1);
    expect(result).toEqual({ time: 1, x: 10, row: 1 });
  });

  it("should never report a smaller x while still on the same row across a row-boundary bracket", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const beforeBoundary = interpolatePlayheadX(rowChangePoints, 0.9)!;
    const atBoundary = interpolatePlayheadX(rowChangePoints, 1)!;

    expect(beforeBoundary.row).toBe(0);
    expect(beforeBoundary.x).toBe(190);
    expect(atBoundary.row).toBe(1);
  });

  it("should still interpolate x smoothly between two points on the same row", () => {
    const samRowPoints: TimelinePoint[] = [
      { time: 0, x: 10, row: 2 },
      { time: 1, x: 210, row: 2 },
    ];
    const result = interpolatePlayheadX(samRowPoints, 0.5);
    expect(result).toEqual({ time: 0.5, x: 110, row: 2 });
  });
```

(The last test pins down that same-row interpolation, which is correct and not part of the bug, keeps working unchanged.)

- [ ] **Step 2: Run the tests to verify the new/changed ones fail**

Run: `cd frontend && pnpm test -- timeline.test.ts`
Expected: FAIL on `"should hold at the old row's last point..."` and `"should never report a smaller x..."` — current code returns `{x: 100, row: 0}` at `time=0.5`, not `{x: 190, row: 0}`.

- [ ] **Step 3: Fix `interpolatePlayheadX`**

In `frontend/lib/notation/timeline.ts`, replace the bracket-matching loop body:

```ts
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (time >= a.time && time <= b.time) {
      // Unreachable while points are sorted by non-decreasing time: any
      // pair sharing a.time with an earlier point would already have been
      // matched (and returned) by that earlier bracket first. Guards
      // against a division by zero if that invariant is ever broken.
      if (b.time === a.time) {
        return a;
      }
      const ratio = (time - a.time) / (b.time - a.time);
      return { time, x: a.x + (b.x - a.x) * ratio, row: a.row };
    }
  }
```

with:

```ts
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (time >= a.time && time <= b.time) {
      if (a.row !== b.row) {
        // A new row restarts at the left margin while the previous row's
        // last slot sits at the right edge - their x-coordinates are
        // unrelated, so interpolating between them would slide the
        // playhead backward through the old row before cutting to the
        // new one. Hold at the old row's last point until the new row's
        // first point's time is reached, then cut straight to it.
        return time >= b.time ? b : a;
      }
      if (b.time === a.time) {
        return a;
      }
      const ratio = (time - a.time) / (b.time - a.time);
      return { time, x: a.x + (b.x - a.x) * ratio, row: a.row };
    }
  }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && pnpm test -- timeline.test.ts`
Expected: PASS (all tests in the file, including the pre-existing same-row interpolation and clamping tests — no regressions).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/notation/timeline.ts frontend/lib/notation/__tests__/timeline.test.ts
git commit -m "fix: stop interpolating playhead x across a score row change"
```

---

### Task 2: Component-level regression test proving the playhead never jumps backward across a real multi-row score

**Files:**
- Test: `frontend/components/__tests__/DrumScore.test.tsx`

**Interfaces:**
- Consumes: existing `DrumScore` component, unchanged props (`events`, `tempoBpm`, `currentTime`).

This exercises the fix through the real rendering path (VexFlow layout -> `getAbsoluteX()` -> `timelineRef` -> `interpolatePlayheadX` -> the SVG `<line>` element), closer to what a human would see, as a practical stand-in for a full live-browser run given a real job requires network access (YouTube download) and heavy processing (Demucs/DrumScript) this plan does not otherwise need.

- [ ] **Step 1: Write the failing test**

Append to `frontend/components/__tests__/DrumScore.test.tsx`:

```tsx
  it("should never move the playhead backward in x while stepping through a real multi-row score", () => {
    // MEASURES_PER_ROW is 4, so measure 5 starts a second row.
    const events = [
      event({ id: "1", measure: 4, beat: 4, subdivision: 3, instrument: "kick" }),
      event({ id: "2", measure: 5, beat: 1, subdivision: 0, instrument: "snare" }),
    ];
    const secondsPerSixteenth = 60 / 120 / 4;
    const measure4Beat4Sub3Time = (3 * 4 + 3 + 3) * secondsPerSixteenth; // measure/beat/subdivision -> seconds at 120bpm
    const measure5Beat1Sub0Time = 4 * 4 * secondsPerSixteenth;

    const { rerender } = render(
      <DrumScore tempoBpm={120} currentTime={0} events={events} />,
    );
    const container = screen.getByTestId("drum-score");

    const sampleTimes = [
      measure4Beat4Sub3Time - 0.05,
      measure4Beat4Sub3Time,
      (measure4Beat4Sub3Time + measure5Beat1Sub0Time) / 2,
      measure5Beat1Sub0Time,
    ];

    let previousX: number | null = null;
    let previousY: number | null = null;
    for (const time of sampleTimes) {
      rerender(<DrumScore tempoBpm={120} currentTime={time} events={events} />);
      const line = container.querySelector("#drum-score-playhead")!;
      const x = Number(line.getAttribute("x1"));
      const y = Number(line.getAttribute("y1"));

      if (previousX !== null && previousY === y) {
        expect(x).toBeGreaterThanOrEqual(previousX);
      }
      previousX = x;
      previousY = y;
    }
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- DrumScore.test.tsx -t "never move the playhead backward"`
Expected: FAIL before Task 1's fix is present. (If Task 1 is already merged when this step runs, temporarily revert `timeline.ts`'s fix locally to confirm this test catches the regression, then restore it — do not skip this verification.)

- [ ] **Step 3: Run the full frontend test suite to verify it passes with Task 1's fix in place**

Run: `cd frontend && pnpm test`
Expected: PASS, no regressions across any existing test file (`DrumScore.test.tsx`, `Player.test.tsx`, `timeline.test.ts`, `buildScore.test.ts`, `buildStaveNote.test.ts`, `SyncedPlayer.test.ts`, `loadAudioBuffer.test.ts`, `jobs.test.ts`, `JobForm.test.tsx`, `EndToEndFlow.test.tsx`).

- [ ] **Step 4: Run lint and typecheck**

Run: `cd frontend && pnpm lint`
Run: `cd frontend && npx tsc --noEmit`
Expected: both clean (no new errors introduced).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/__tests__/DrumScore.test.tsx
git commit -m "test: add multi-row playhead regression coverage for DrumScore"
```

---

## Self-Review Notes

- **Spec coverage:** "Reproduction steps and root cause are documented" -> this plan's root-cause section (carried into the PR description) with exact file:line references and concrete numbers. "Regression test exists where practical" -> Task 1 (unit-level, `interpolatePlayheadX`) and Task 2 (component-level, `DrumScore`) - both practical, both automated. "Fix addresses root cause" -> Task 1 changes only the proven-buggy function, nothing else. "Playhead moves monotonically except explicit seek/loop" -> verified by Task 1/2 tests. "Full-song manual verification passes" -> addressed as a limitation in the PR: a real end-to-end manual check requires a processed job with real audio (YouTube download + Demucs + DrumScript), which needs explicit confirmation before spending that time/network budget; the component-level test in Task 2 is the closest automated stand-in and exercises the identical code path a live browser session would.
- **Ruled out, not guessed:** unstable `events` reference (traced `Player.tsx` -> `DrumScore` prop passing: stable), tempo drift / non-constant-tempo (current architecture only has one constant BPM end-to-end, so within a row the timeline is provably monotonic by construction) - both documented above so this isn't re-litigated later.
- **Type consistency:** `TimelinePoint` shape (`{ time, x, row }`) unchanged; `interpolatePlayheadX`'s signature and null-return contract unchanged, so no caller (`DrumScore.tsx`) needs updating.
