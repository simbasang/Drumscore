# Notation golden fixtures (V1-022)

Six representative grooves in `frontend/lib/notation/__fixtures__/grooves.ts`
(`GROOVE_FIXTURES`), covering Epic 4's exit gate: "representative grooves
render as conventional readable drum notation." Each fixture is a plain
`AnalysisEvent[]`, consumed two ways:

- `frontend/lib/notation/__tests__/goldenFixtures.test.ts` — structural
  engraving-property assertions (stem direction, notehead keys, simultaneous
  grouping, rest/duration consolidation) run directly against the
  `fromAnalysisEvents` → `buildStaveNote` pipeline, independent of rendering.
- `frontend/components/__tests__/DrumScore.fixtures.test.tsx` — a full-render
  smoke pass per fixture through the real `DrumScore` component, asserting it
  renders without throwing and produces the expected number of stave-note
  elements.

These automated checks catch structural and integration regressions, but
they can't catch something that renders correctly by every assertion and
still looks wrong. The checklist below is for a human to run manually
against the live app whenever Epic 4's notation output changes materially.

## How to run it manually

There's no permanent fixture-viewer route (kept out of scope per YAGNI —
see the V1-022 PR). Temporarily import a fixture's `events` from
`grooves.ts` into `app/page.tsx` (or wherever `DrumScore` is mounted) in
place of live job data, view it in a real browser, then revert the
temporary change before committing — the same technique used to manually
verify V1-021's adaptive layout.

## Checklist (per fixture)

For each of the six fixtures, verify by eye:

- [ ] Five-line percussion staff, correct clef/time signature placement
- [ ] Every stem points upward, including kick and snare
- [ ] Simultaneous hits render as one aligned/grouped note, not overlapping separate notes
- [ ] Closed vs. open hi-hat are visually distinguishable only by notehead shape (plain X vs. circled X), same staff position
- [ ] Note/rest durations read as normal musical values (quarters, eighths, etc.), not a wall of sixteenths
- [ ] Beams group by beat, not by measure or arbitrarily
- [ ] Layout looks legible with no obvious visual defects (overlapping glyphs, misaligned noteheads, clipped stems)

## Fixture-specific checks

- **sparseBackbeat** — four evenly-spaced quarter notes (kick/snare), clear space between them, no crowding.
- **denseSixteenths** — sixteen closed hi-hat notes beamed in beat-sized groups of four, staff not overcrowded.
- **restStretch** — a quarter rest, a quarter note, then a half rest — confirms rests consolidate into the fewest correct symbols instead of a run of sixteenth rests.
- **simultaneousHits** — kick+snare+hihat_closed on beat 1 render as a single chord (one stem, three noteheads at their respective staff positions).
- **openHihatAlternation** — alternating plain-X and circled-X noteheads at the same staff line, unambiguous at a glance.
- **tomFill** — descending tom_high → tom_mid → tom_low → snare sixteenth run on beat 4, beamed together, reads as a fill distinct from the backbeat before it.

## Epic 4 gate

Epic 4's exit gate ("representative grooves render as conventional readable
drum notation") is considered verified once both the automated suite above
is green and this checklist has been run manually at least once against a
real rendered app for all six fixtures.
