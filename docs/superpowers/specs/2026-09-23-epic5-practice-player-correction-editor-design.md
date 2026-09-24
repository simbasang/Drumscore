# Epic 5 — Practice Player & Correction Editor — design

Issues: #74 (V1-023), #75 (V1-024), #76 (V1-025), #77 (V1-026), #78
(V1-027), #79 (V1-028), all part of EPIC 5 (#32). Implemented as ONE
bundled PR — a user-approved one-time exception to the normal
one-issue-per-branch workflow (same precedent as Epic 3's PR #101).

## Goal

A user can click notation to seek, loop a section, change practice
speed, get a count-in/metronome anchored to real beats, manually
correct drum events, review/accept low-confidence hits, and undo/redo
edits — without leaving Drumscore. Exit gate per PROJECT.md: "a user
can generate, correct and practise a song without leaving Drumscore."

## Current state

- `frontend/lib/audio/SyncedPlayer.ts`: owns two synced stem buffers,
  offset/play/pause/seek/volume. No loop, no rate, no metronome.
- `frontend/components/Player.tsx`: rAF-driven UI wrapper around
  `SyncedPlayer`; passes raw `events`/`currentTime` to `DrumScore`.
- `frontend/components/DrumScore.tsx`: calls `fromAnalysisEvents(events)`
  fresh inside its render effect every time `events`/`containerWidth`
  changes — there is no persistent, stateful `Score` anywhere. No click
  handling on rendered notes.
- `frontend/lib/score/transformations.ts` (`addHit`/`deleteHit`/
  `moveHit`/`changeInstrument`) and `frontend/lib/score/serialization.ts`
  already exist and are unit-tested (landed in V1-017/#50) but are wired
  into no UI or state anywhere yet.
- `frontend/lib/notation/timeline.ts`: `interpolatePlayheadX` /
  `computeAutoScrollLeft` already handle playhead positioning and
  horizontal auto-scroll, including not sliding the playhead backward
  across an x-decreasing row break.
- Backend: `backend/app/job_processor.py` computes real per-beat
  timestamps (`job.beats: list[BeatPoint]`, source_time + measure + beat)
  during tempo mapping and stores them on the job, but no API route
  returns them — `GET /api/jobs/{id}/analysis` (`backend/app/api/jobs.py`,
  `AnalysisResponse`) returns only a scalar `tempo_bpm` and `events`.
  Only `GET /api/jobs/{id}/diagnostics` consumes `job.beats` server-side,
  and even that endpoint doesn't return the raw beat list itself.
- `backend/app/transcription.py`: `DrumEvent.confidence` is `None` unless
  an engine has "a defensible confidence signal" — the production
  `DrumScriptTranscriber` never sets it, so real jobs have
  `confidence: null` on every event today (Epic 3 finding).

## Non-goals (explicit scope-out)

- **Real pitch-preserving time-stretch.** Playback rate uses native
  `AudioBufferSourceNode.playbackRate`, which shifts pitch with speed.
  Documented as a known v1 limitation per #76's own acceptance criteria
  ("limitations documented"), not fixed with a third-party stretch
  library/AudioWorklet.
- **Sample-accurate loop restart scheduling.** Loop restart is
  poll-based (detected on the existing rAF tick, ~16ms worst-case
  jitter), not a lookahead-scheduled gapless restart.
- **Persisting corrections/undo history to the backend.** Epic 5's
  issues don't ask for it; PROJECT.md puts durable project/job storage
  in Epic 6. Edits live in React state for the session only.
- **Count-in on loop restarts.** Count-in plays once before the first
  `play()` from a stopped state; looping/seeking during playback does
  not re-trigger it.
- **Undo/redo for playback settings.** Only correction-editor edits
  (add/delete/move/change-instrument) are undo-tracked; loop bounds,
  rate, and volume are direct-manipulation UI state.
- **Growing the score to create new measures.** `insertHit`'s existing
  limitation (TECHNICAL_DEBT.md, V1-018) is fixed in this epic only if
  the new editor UI actually makes it reachable (see "Known gap" below);
  otherwise it stays deferred as already documented.
- **Backend persistence/durability work of any kind** (Epic 6 territory)
  beyond the additive, already-computed `beats` field below.

## Backend: expose beat anchors

`backend/app/api/jobs.py`:

```python
class BeatResponse(BaseModel):
    source_time: float
    measure: int
    beat: int

    @classmethod
    def from_beat_point(cls, beat: BeatPoint) -> "BeatResponse":
        return cls(source_time=beat.source_time, measure=beat.measure, beat=beat.beat)


class AnalysisResponse(BaseModel):
    tempo_bpm: float
    events: list[DrumEventResponse]
    beats: list[BeatResponse] = []
```

`get_job_analysis` passes `beats=[BeatResponse.from_beat_point(b) for b in (job.beats or [])]`.
No new computation — `job.beats` is already populated by
`run_tempo_mapping` whenever beat detection succeeds. A job whose beats
are `None` (analysis available but beat mapping didn't run/store, e.g.
older test fixtures) returns an empty list rather than erroring;
metronome/count-in degrade to disabled rather than the whole player
failing. Downbeat is `beat == 1`, no separate flag needed given
`DEFAULT_BEATS_PER_MEASURE`-based construction already numbers beats
from 1.

Frontend `frontend/lib/api/jobs.ts` gains:

```ts
export interface Beat {
  sourceTime: number;
  measure: number;
  beat: number;
}

export interface Analysis {
  tempo_bpm: number;
  events: AnalysisEvent[];
  beats: Beat[];
}
```

(mapping `source_time` → `sourceTime` in the fetch layer, matching this
codebase's existing camelCase-on-the-frontend convention.)

## Playback transport: `PracticeTransport`

New `frontend/lib/audio/PracticeTransport.ts`, composing (not
replacing) the existing `SyncedPlayer`. `SyncedPlayer` keeps its current
single responsibility (sample-synced two-stem playback) and gains only
one small addition: a `setPlaybackRate(rate: number)` method that sets
`playbackRate.value` on both active `BufferSourceNodeLike` sources (a
no-op on the interface until sources exist; applied to new sources in
`startSources` too) — this requires widening `BufferSourceNodeLike` with
a `playbackRate: { value: number }` field, matching the real
`AudioBufferSourceNode` shape.

`PracticeTransport` owns everything session-level:

```ts
interface LoopRange {
  startTime: number;
  endTime: number;
}

class PracticeTransport {
  constructor(player: SyncedPlayer, beats: Beat[]);

  // Delegates straight to the wrapped SyncedPlayer.
  play(): void;
  pause(): void;
  seek(time: number): void;
  get isPlaying(): boolean;
  get duration(): number;

  // New.
  setLoop(range: LoopRange | null): void;
  getLoop(): LoopRange | null;
  setPlaybackRate(rate: number): void;
  getPlaybackRate(): number;
  setMetronomeEnabled(enabled: boolean): void;
  playWithCountIn(): void;

  // Called from the existing rAF tick instead of player.getCurrentTime().
  tick(): number;
}
```

**Loop restart** (poll-based, per your answer): pure functions,
independently unit-tested with no `AudioContextLike`:

```ts
function shouldRestartLoop(currentTime: number, loop: LoopRange | null): boolean;
function loopRestartOffset(loop: LoopRange): number; // == loop.startTime
```

`tick()` calls `player.getCurrentTime()`, and if `shouldRestartLoop`
returns true, calls `player.seek(loopRestartOffset(loop))` before
returning the corrected time — both stems restart together because
`SyncedPlayer.seek` already stops and restarts both sources from the
same offset in one call; no new stem-sync logic needed here, only the
decision of *when* to call it.

**Playback rate:** `setPlaybackRate` forwards to
`player.setPlaybackRate(rate)`. Because `SyncedPlayer.getCurrentTime()`
computes elapsed time as `offset + (context.currentTime -
startContextTime)` — implicitly assuming rate 1 — changing rate
mid-playback requires rebasing: `PracticeTransport.setPlaybackRate`
calls `player.seek(player.getCurrentTime())` (which the existing `seek`
already implements as stop-and-restart-from-offset) immediately before
changing the rate, so `startContextTime`/`offset` are re-baselined at
the moment of the change. `SyncedPlayer.getCurrentTime()` itself then
needs to multiply the elapsed real-time delta by the current rate
(pure function `elapsedSourceTime(offset, contextDelta, rate)`,
unit-tested), since a rate ≠ 1 makes 1 second of `context.currentTime`
correspond to `rate` seconds of source time consumed.

**Metronome & count-in.** New `frontend/lib/audio/metronomeScheduling.ts`,
pure/testable:

```ts
function beatPeriodAt(beats: Beat[], sourceTime: number): number | null;
function beatsInWindow(beats: Beat[], windowStart: number, windowEnd: number): Beat[];
function countInClickTimes(beats: Beat[], startTime: number, clickCount: number): number[];
```

`beatPeriodAt` finds the local beat interval nearest `sourceTime`
(reusing the same "nearest anchor, interpolate between neighbors" idea
as `interpolatePlayheadX`, but for beat period instead of x-position);
returns `null` if `beats` is empty, in which case the caller disables
metronome/count-in entirely rather than falling back to a fixed BPM
(preserves "no independent fixed-BPM drift").

`PracticeTransport` schedules synthesized clicks (a short `OscillatorNode`
burst through a `GainNode` envelope, no audio asset) via the standard
Web Audio lookahead pattern: a periodic check (driven by the same rAF
tick already running) schedules any click whose time falls within the
next ~100ms using `context.currentTime`-relative `start(when)` calls,
re-deriving anchor times from `beats[]` + current `getCurrentTime()`
plus rate on every check — so a rate change or a loop restart is picked
up on the next check rather than needing separate invalidation logic.
`playWithCountIn()` computes `countInClickTimes` for a fixed count (4,
one measure at `DEFAULT_BEATS_PER_MEASURE`), schedules them starting at
`context.currentTime`, then calls the underlying `play()` timed via
`context.currentTime + totalCountInDuration` so playback starts exactly
as the last click ends.

`Player.tsx` is updated to construct a `PracticeTransport` wrapping its
existing `SyncedPlayer` and call `transport.tick()` from the rAF loop
instead of `player.getCurrentTime()`; new UI controls (loop
set/clear, rate selector, metronome toggle, count-in-play button) are
added alongside the existing play/pause/seek/volume controls.

## Click-to-seek

`DrumScore.tsx` gains an `onSeek?: (time: number) => void` prop. In the
render effect, after `voice.draw()`, each note slot with at least one
real-timestamped hit (the same `times.length === 0` guard already used
for the timeline) gets a click listener on `note.getSVGElement()`
calling `onSeek(averageSourceTime(times))` — the same average-time
computation already used to build the timeline point for that slot, so
clicking a note seeks to exactly where its own playhead anchor sits.
Slots with no real-timestamped hits (rests; manually-added hits with
`time: null`) get no listener.

`Player.tsx` passes `onSeek={(time) => transport.seek(time)}`, updating
`currentTime` the same way the existing seek slider does — loop/rate
state is untouched by a seek, matching "seek behavior predictable" in
#75's own acceptance criteria.

The "row changes do not jump backward" criterion is verified against
existing `interpolatePlayheadX` behavior (already handles x-decreasing
row breaks by holding position rather than sliding backward, per its
existing comment) under the new loop/rate paths; covered by regression
tests plus real-browser manual verification rather than assumed.

## Editable score state

**Structural change:** `DrumScore.tsx` stops calling `fromAnalysisEvents`
itself. Its prop changes from `events: AnalysisEvent[]` to
`score: Score`; it purely renders whatever `Score` it's given.
`docs/ARCHITECTURE_V1.md`'s engraving section is updated to reflect this
(engraving already says it "never operates directly on
DrumScript/VexFlow structures" — this makes explicit that it also
doesn't own score construction).

New `frontend/lib/score/useScoreEditor.ts`:

```ts
function useScoreEditor(events: AnalysisEvent[]): {
  score: Score;
  addHit: (position: MusicalPosition, instrument: DrumInstrument) => void;
  deleteHit: (hitId: string) => void;
  moveHit: (hitId: string, newPosition: MusicalPosition) => void;
  changeInstrument: (hitId: string, newInstrument: DrumInstrument) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
};
```

Builds `Score` once via `fromAnalysisEvents(events)` on mount / when
`events` identity changes (new job), holds it in `useState`. Each
mutating call pushes the *current* `Score` onto an undo stack, applies
the corresponding pure `transformations.ts` function, and clears the
redo stack; `undo`/`redo` pop/push between the two stacks. No deep
cloning — `Score` objects are already immutable-by-convention (every
`transformations.ts` function returns a new object), so a stack entry
is just a reference.

`Player.tsx` owns the hook and passes `score` to `DrumScore`, plus the
edit callbacks to a new correction-editor UI (a toolbar/side panel:
select a hit → delete/move/change-instrument; an "add hit" mode that
picks position+instrument then calls `addHit`). Source vs. edited state
is already representable without new fields — `addHit` stamps
`provenance: "manual"`, `sourceEventId: null`, `time: null`; the UI
renders manual hits with a distinguishing style (e.g. an outline or
different fill on the notehead, via a small addition to
`buildStaveNote.ts`/`instrumentNotation.ts` keyed on
`hit.sourceEventId == null`). Manual hits contribute no timeline point
(same `time == null` guard as click-to-seek), so they cannot corrupt
score following — "no audio reprocessing needed" and "playback remains
aligned" hold by construction, not by extra logic.

**Known gap to resolve in-scope if reachable:** `insertHit`
(`frontend/lib/score/transformations.ts`) currently no-ops silently if
`position.measure` exceeds `score.measures.length` (TECHNICAL_DEBT.md,
V1-018). The new "add hit" UI will be implemented against real
editable-score UI for the first time; I'll confirm during
implementation whether a user can actually reach an out-of-range
position (e.g. adding past a short song's last measure) and fix
`insertHit` to extend `score.measures` with rest-filled measures if so,
rather than ship a silent no-op behind a real UI action.

## Confidence-assisted review

New `frontend/lib/score/confidence.ts`:

```ts
export const LOW_CONFIDENCE_THRESHOLD = 0.5;
export function isLowConfidence(hit: ScoreHit): boolean {
  return hit.confidence != null && hit.confidence < LOW_CONFIDENCE_THRESHOLD;
}
```

A single documented tunable rather than a magic number in JSX.
`buildStaveNote.ts` applies a distinct visual style (amber
notehead/outline) only when `isLowConfidence(hit)` is true — a
`confidence: null` hit (the real-world case for every hit today, per
Epic 3) renders identically to any other hit, never a fabricated
indicator. A flagged hit gets an "accept" affordance in the correction
UI that sets `confidence` to a value ≥ threshold (reusing
`changeInstrument`-style in-place field update, no new transformation
needed) — actual *correction* of a flagged hit is just the existing
move/delete/change-instrument ops.

Because production confidence is `null` today, this feature is verified
against a **synthetic fixture with non-null low-confidence hits**
(`frontend/lib/score/__fixtures__/` or similar) so it's provably
correct even though it won't visibly trigger on real jobs yet — called
out explicitly in the PR description as dormant-but-correct pending
real confidence data from a future transcription-engine change.

## File layout

```
frontend/lib/audio/
  SyncedPlayer.ts              (+ setPlaybackRate, rate-aware getCurrentTime)
  PracticeTransport.ts          (new)
  metronomeScheduling.ts        (new)
  __tests__/
    SyncedPlayer.test.ts        (extended: rate)
    PracticeTransport.test.ts   (new)
    metronomeScheduling.test.ts (new)

frontend/lib/score/
  useScoreEditor.ts              (new)
  confidence.ts                  (new)
  __tests__/
    useScoreEditor.test.ts       (new)
    confidence.test.ts           (new)
  __fixtures__/
    lowConfidenceGroove.ts       (new, synthetic)

frontend/components/
  DrumScore.tsx        (events prop -> score prop; +onSeek; +manual/low-confidence styling)
  Player.tsx            (owns PracticeTransport + useScoreEditor; +loop/rate/metronome/editor UI)
  __tests__/
    DrumScore.test.tsx   (extended: onSeek, score prop, styling)
    Player.test.tsx       (extended: loop/rate/metronome/editor controls)

backend/app/api/jobs.py           (+BeatResponse, AnalysisResponse.beats)
backend/tests/test_jobs_api.py     (extended: beats round-trip)
```

## Testing plan

- `PracticeTransport`/`metronomeScheduling`: pure-function unit tests
  (`shouldRestartLoop`, `loopRestartOffset`, `elapsedSourceTime`,
  `beatPeriodAt`, `beatsInWindow`, `countInClickTimes`) with no
  `AudioContextLike`. Integration tests against the same mock
  `AudioContextLike`/`BufferSourceNodeLike` pattern `SyncedPlayer.test.ts`
  already uses, asserting loop restart calls stop+start on both stems
  together and rate changes rebase offset correctly.
- Click-to-seek: `DrumScore.test.tsx` case asserting a simulated click
  on a rendered note element fires `onSeek` with that slot's exact
  average source time; a rest/manual-hit slot fires nothing.
- `useScoreEditor`: `renderHook` tests covering each operation, undo/redo
  sequences, and redo-stack-clearing on a new edit after an undo.
- `confidence.ts`: table-driven tests (null / above / below threshold).
- Backend: extend `test_jobs_api.py`'s analysis-endpoint tests with a
  case asserting `beats` round-trips from a job with `job.beats` set,
  and an empty-list case when `job.beats` is `None`.
- Manual real-browser verification (Playwright, temporary debug route
  removed before commit), per CLAUDE.md's rule that this repo's
  automated suite has a structural blind spot around rendered geometry
  and audio timing: click-to-seek hit targets, audible loop-restart
  behavior, metronome click alignment against a real beat track,
  count-in timing, playback-rate audible pitch shift (confirming it's
  the documented limitation, not a bug), row-change playhead behavior
  under loop/rate.

## Migration notes

Same-PR swap, consistent with this repo's stated migration approach
only where a genuinely parallel path would add complexity without
benefit: `DrumScore.tsx`'s `events` prop is replaced by `score` in the
same change that introduces `useScoreEditor`, since there is exactly
one production consumer (`Player.tsx`) and no external contract to keep
stable mid-transition. The backend `beats` field is purely additive
(new optional-with-default field on an existing response), so no
existing consumer needs to change.
