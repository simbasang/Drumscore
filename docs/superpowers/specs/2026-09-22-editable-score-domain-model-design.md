# Editable score domain model — design

Issue: #50 (V1-017), part of EPIC 4 — Notation Engine 2.0 (#31).

## Goal

Introduce an application-owned score model between timing analysis and
engraving: durations, rests, simultaneous hits, source-event links and
confidence/provenance metadata, with transformation functions for future
manual edits (Epic 5) and JSON serialization. VexFlow stays out of the
model entirely.

## Current state

`frontend/lib/notation/buildScore.ts` already does most of the grouping
work: `buildMeasures(events: AnalysisEvent[])` groups `AnalysisEvent`s by
`measure:beat:subdivision`, builds one `NoteSpec` per occupied 16th-grid
slot (merging simultaneous instruments into one `keys[]`/`articulations[]`
pair), fills gaps with `RestSpec`, and consolidates consecutive rests into
the fewest tied values. `buildStaveNote.ts` converts a `SlotSpec` straight
into a VexFlow `StaveNote`. `DrumScore.tsx` calls `buildMeasures` directly
and reads `NoteSpec.sourceTimes` to build the playhead timeline.

Gaps relative to what EPIC 4 needs:
- `NoteSpec`/`RestSpec` have no stable IDs, so nothing can be selected,
  deleted, or moved.
- No confidence/provenance, even though the backend's
  `GET /api/jobs/{id}/analysis` response already includes both
  (`DrumEventResponse.confidence`, `.provenance`, `backend/app/api/jobs.py`)
  — the frontend's `AnalysisEvent` type (`frontend/lib/api/jobs.ts`) just
  drops them.
- No transformation functions (add/delete/move/change-instrument).
- No serialization.
- Types live in `lib/notation/`, mixed in with the VexFlow-facing
  `buildStaveNote.ts`, blurring the domain/engraving boundary.

## Non-goals (explicitly out of scope for #50)

- Deriving real note durations from occupied positions (quarter/eighth/
  etc.) — that's #51 (V1-018). This issue keeps every hit at a fixed `"16"`
  duration, same as today; the model's `duration` field just stops being
  hardcoded at the type level so #51 can start producing other values
  without another model change.
- Beaming/grouping rules — #52 (V1-019).
- Hi-hat/cymbal notation fidelity — #53 (V1-020).
- Adaptive layout/line breaking — #72 (V1-021).
- Golden/reference regression suite — #73 (V1-022).
- Any Epic 5 editor UI. This issue ships the transformation *functions*
  only, unit-tested directly; nothing calls them from a component yet.
- Backend changes. `confidence`/`provenance` are already returned by the
  API; only the frontend type and domain model need to stop dropping them.
- Changing how many measures a score has. Transformations edit slot
  contents within the measures produced by construction; they never add or
  remove measures (that would require reasoning about song duration, which
  this model doesn't own).

## Data model

New module: `frontend/lib/score/types.ts`.

```ts
export type Provenance = string; // backend engine name (e.g. "drumscript") or "manual"

export interface MusicalPosition {
  measure: number;
  beat: number;
  subdivision: number;
}

export interface ScoreHit {
  id: string;
  sourceEventId: string | null; // null for a manually added hit
  time: number | null;          // immutable source timestamp; null for a manually added hit
  instrument: DrumInstrument;
  confidence: number | null;
  provenance: Provenance;
}

export interface ScoreNote {
  type: "note";
  id: string;
  position: MusicalPosition;
  duration: string;   // VexFlow-style duration string ("16", "8", "4", ...) - a plain
                       // rhythm-value encoding, not a VexFlow type; no vexflow import here
  hits: ScoreHit[];    // 1+ simultaneous hits at this position
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

Design notes:
- **The hit, not the note, is the atomic editable unit.** A `ScoreNote` is
  a derived grouping of one or more `ScoreHit`s that share a musical
  position — that's what "simultaneous hits are first-class" means here:
  you never have to re-derive the grouping yourself, but the thing you
  add/delete/move/re-instrument is a single hit. Moving one hit out of a
  three-hit note leaves a two-hit note behind; moving the last hit out
  turns the slot into a rest.
- **Source links survive independent edits.** `sourceEventId`/`time` on a
  `ScoreHit` are set once at construction from the originating
  `AnalysisEvent` and never rewritten by any transformation — including
  `moveHit`, which relocates the position but keeps the same hit id and
  source link. Only a hit's own `changeInstrument`/`moveHit` call touches
  that hit; every other hit in the score is untouched by construction.
  This is the direct analogue of CLAUDE.md's "every event keeps an
  immutable original source timestamp" rule, scoped to this model: a
  hit's original `time`/`sourceEventId` are write-once, even though its
  *musical* position (which slot it renders into) can change under edit.
- Manually added hits (via `addHit`, once Epic 5 wires up a UI) get
  `sourceEventId: null`, `time: null`, `provenance: "manual"` — there is
  no source event to link.
- No VexFlow types or imports anywhere in `frontend/lib/score/`.

## Construction

`frontend/lib/score/buildScore.ts`: `fromAnalysisEvents(events: AnalysisEvent[]): Score`.

Ports today's `buildMeasures` almost unchanged: group placeable events
(non-null `measure`/`beat`/`subdivision`) by position, build one
`ScoreNote` per occupied slot (one `ScoreHit` per event, each carrying that
event's `id` as `sourceEventId`, its `time`, `confidence`, and
`provenance`), fill gaps with `ScoreRest`, run the same
`consolidateRests` merge. Slot/hit `id`s are generated at construction
(`crypto.randomUUID()`).

`AnalysisEvent` (`frontend/lib/api/jobs.ts`) gains the two fields the
backend already sends:

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

## Transformations

New module: `frontend/lib/score/transformations.ts`. Pure functions,
each returning a new `Score` (no in-place mutation, consistent with the
rest of the codebase's functional style):

- `addHit(score, position, instrument): Score` — inserts a manually
  added hit (`provenance: "manual"`, `sourceEventId: null`, `time: null`,
  `confidence: null`) at `position`. If a `ScoreNote` already occupies
  that slot, the hit joins it; if it's currently a rest, the rest run is
  split/re-consolidated around the new one-hit note, reusing the existing
  slot-expand-then-`consolidateRests` approach.
- `deleteHit(score, hitId): Score` — removes one hit. If it was the only
  hit at that slot, the slot becomes a rest and the measure's rests are
  re-consolidated.
- `moveHit(score, hitId, newPosition): Score` — relocates one hit to a
  (possibly different-measure) slot, preserving its id/sourceEventId/
  time/confidence/provenance. Implemented as delete-then-add of the same
  hit record, not as delete-then-fabricate.
- `changeInstrument(score, hitId, newInstrument): Score` — updates a
  hit's `instrument` in place; position/source link/confidence/provenance
  untouched.

All four operate at slot (16th-grid) granularity — consistent with the
grid quantization already fixes positions to.

## Serialization

New module: `frontend/lib/score/serialization.ts`:
`toJSON(score: Score): unknown` / `fromJSON(json: unknown): Score`. Plain
JSON-serializable round trip (no class instances anywhere in the model to
begin with, so this is mostly a documented, tested identity/validation
boundary for future persistence — not wired to any API in this issue).

## Integration changes

- `frontend/components/DrumScore.tsx`: `buildMeasures` import moves from
  `@/lib/notation/buildScore` to `@/lib/score/buildScore`
  (`fromAnalysisEvents`); `measure.map(buildStaveNote)` becomes
  `score.measures[i].map(buildStaveNote)`; `averageSourceTime(slot.sourceTimes)`
  becomes `averageSourceTime(slot.hits.map(h => h.time).filter(t => t != null))`.
- `frontend/lib/notation/buildStaveNote.ts`: import `Slot`/`ScoreNote`/
  `ScoreRest` from `@/lib/score/types` instead of `SlotSpec` from
  `./buildScore`; reads `slot.hits` (mapping to VexFlow `keys`/
  `articulations` via `INSTRUMENT_NOTATION`) instead of `slot.keys`/
  `slot.articulations` directly, since those are no longer precomputed on
  the note.
- `frontend/lib/notation/buildScore.ts` (old file) is deleted; its
  construction logic lives in `frontend/lib/score/buildScore.ts` now.
  `frontend/lib/notation/instrumentNotation.ts` and `timeline.ts` are
  unaffected (pure engraving/playhead concerns) and stay where they are.
- `frontend/lib/api/jobs.ts`: `AnalysisEvent` gains `confidence` and
  `provenance` as shown above.

## File layout

```
frontend/lib/score/
  types.ts
  buildScore.ts          (fromAnalysisEvents)
  transformations.ts      (addHit/deleteHit/moveHit/changeInstrument)
  serialization.ts        (toJSON/fromJSON)
  __tests__/
    buildScore.test.ts
    transformations.test.ts
    serialization.test.ts
```

`frontend/lib/notation/` keeps `buildStaveNote.ts`, `instrumentNotation.ts`,
`timeline.ts` and their tests — the engraving/playback-adjacent layer,
now consuming `@/lib/score/types` instead of owning its own slot types.

## Testing plan

- `buildScore.test.ts`: ports today's `buildScore.test.ts` cases
  (simultaneous hits, rest consolidation, empty input) plus new coverage
  for confidence/provenance pass-through and stable id generation.
- `transformations.test.ts`: each of the four operations, including:
  simultaneous-hit grouping and ungrouping (add into an occupied slot;
  delete down to zero hits), rest re-consolidation after add/delete/move,
  and — directly testing the source-link-survives-edits rule — that
  editing one hit leaves every other hit's `id`/`sourceEventId`/`time`
  byte-for-byte unchanged.
- `serialization.test.ts`: round-trip `toJSON` → `fromJSON` produces a
  deep-equal `Score`, for both a freshly constructed score and one that's
  been through transformations.
- Update `buildStaveNote.test.ts` to build fixtures against the new
  `ScoreNote`/`ScoreRest` shape.
- Update `DrumScore.test.tsx`/`EndToEndFlow.test.tsx` for the new
  `AnalysisEvent` fields and the `DrumScore.tsx` integration change (no
  behavioral change expected — same rendered output for the same input
  events).

## Migration notes

This is a same-PR swap, not a parallel-path migration: `buildScore.ts` in
`lib/notation/` is deleted and every consumer (`DrumScore.tsx`,
`buildStaveNote.ts`, their tests) is updated in the same change, since
there's exactly one production consumer of the old shape and no external
contract to keep stable during a transition.
