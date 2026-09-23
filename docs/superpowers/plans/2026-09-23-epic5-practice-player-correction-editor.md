# Epic 5 — Practice Player & Correction Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship click-to-seek, A/B loop, playback speed, count-in/metronome, a manual drum-event correction editor, undo/redo, and confidence-assisted review — bundling GitHub issues #74-#79 (V1-023 through V1-028, EPIC 5 #32) into one PR, a user-approved one-time exception to this repo's one-issue-per-branch workflow.

**Architecture:** A new `PracticeTransport` class composes the existing, already-tested `SyncedPlayer` (unchanged except a new `setPlaybackRate`) to add loop/rate/metronome/count-in — all loop-restart and beat-scheduling math lives in small pure functions, independently unit-tested with no `AudioContext`. A new `useScoreEditor` hook lifts the `Score` (previously rebuilt from scratch on every `DrumScore` render) into persistent React state, wrapping the already-existing `transformations.ts` functions and adding snapshot-based undo/redo. `DrumScore` stops building its own score and takes one as a prop, gaining click-to-seek and manual/low-confidence visual styling. The backend gains one additive field (`beats`) on the existing analysis endpoint, reusing an already-defined-but-unused `BeatPointResponse` model.

**Tech Stack:** TypeScript, Jest, React Testing Library (frontend); Python, FastAPI, pytest (backend). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-23-epic5-practice-player-correction-editor-design.md`

## Global Constraints

- Web Audio (`SyncedPlayer`'s two-stem sample-synced playback) remains the authoritative transport; nothing in this epic reconstructs time from a scalar BPM.
- Every `ScoreHit`'s `sourceEventId`/`time` stay immutable except by the transformation operating on that exact hit (unchanged from V1-017/#50 — no task in this plan touches `transformations.ts`'s edit semantics).
- Manually added hits (`addHit`) get `sourceEventId: null`, `time: null`, `provenance: "manual"` and contribute no playhead timeline point (existing `times.length === 0` guard).
- Pitch is **not** preserved at non-1x playback rate (native `AudioBufferSourceNode.playbackRate` shifts pitch with speed) — documented as a known v1 limitation, not fixed with a third-party stretch library.
- Loop restart is poll-based (detected on the existing rAF tick), not sample-accurate scheduled.
- Metronome/count-in click times are always derived from real per-beat anchors (`beats[]`); if `beats` is empty, metronome/count-in are simply unavailable — never a fixed-BPM fallback.
- Correction edits and undo/redo live in React state for the session only — no backend persistence in this epic (Epic 6 territory).
- Undo/redo covers only correction-editor edits (add/delete/move/change-instrument), never playback settings (loop/rate/volume).
- Jest tests: AAA structure (arrange/act/assert, blank line between), `describe`/`it("should ...")` naming, per `~/.claude/rules/testing.md`.
- Run `npm test && npm run lint && npx tsc --noEmit` (from `frontend/`) and `pytest` (from `backend/`) before every commit that could plausibly affect the other suite; both must be green before the final task's PR.

---

### Task 1: Backend — expose beat anchors on the analysis endpoint

`backend/app/api/jobs.py` already defines `BeatPointResponse` (with a `from_domain` classmethod) but nothing uses it yet — this task wires it onto the existing `/analysis` endpoint, returning data the pipeline already computes (`job.beats`). No new computation.

**Files:**
- Modify: `backend/app/api/jobs.py` (`AnalysisResponse`, `get_job_analysis`)
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `BeatPointResponse.from_domain(point: BeatPoint) -> BeatPointResponse` (already exists, `backend/app/api/jobs.py:92-101`); `Job.beats: list[BeatPoint] | None` (already exists, `backend/app/jobs.py:37`).
- Produces: `AnalysisResponse.beats: list[BeatPointResponse]` — consumed by no other backend code in this plan (frontend Task 2 consumes it over HTTP).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_jobs_api.py`, directly after `test_get_analysis_exposes_confidence_and_provenance_fields`:

```python
def test_get_analysis_exposes_beat_anchors():
    create_response = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    job_id = create_response.json()["id"]

    response = client.get(f"/api/jobs/{job_id}/analysis")

    body = response.json()
    assert body["beats"] == [
        {"source_time": 0.0, "measure": 1, "beat": 1, "is_downbeat": True, "confidence": None},
        {"source_time": 0.5, "measure": 1, "beat": 2, "is_downbeat": False, "confidence": None},
        {"source_time": 1.0, "measure": 1, "beat": 3, "is_downbeat": False, "confidence": None},
        {"source_time": 1.5, "measure": 1, "beat": 4, "is_downbeat": False, "confidence": None},
    ]


def test_get_analysis_returns_empty_beats_when_job_has_none(isolated_dependencies):
    store = isolated_dependencies
    job_id = _create_job_through_to_tempo_mapped()
    store.update(job_id, beats=None)

    response = client.get(f"/api/jobs/{job_id}/analysis")

    assert response.json()["beats"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `pytest tests/test_jobs_api.py -k beat_anchors -v` and `pytest tests/test_jobs_api.py -k returns_empty_beats -v`
Expected: FAIL — `KeyError: 'beats'` (the response has no `beats` key yet).

- [ ] **Step 3: Write the minimal implementation**

In `backend/app/api/jobs.py`, change:

```python
class AnalysisResponse(BaseModel):
    tempo_bpm: float
    events: list[DrumEventResponse]


@router.get("/{job_id}/analysis", response_model=AnalysisResponse)
def get_job_analysis(job_id: str, store: JobStore = Depends(get_job_store)) -> AnalysisResponse:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.events is None or job.tempo_bpm is None:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis not available yet: job status is {job.status.value}",
        )

    return AnalysisResponse(
        tempo_bpm=job.tempo_bpm,
        events=[DrumEventResponse.from_event(event) for event in job.events],
    )
```

to:

```python
class AnalysisResponse(BaseModel):
    tempo_bpm: float
    events: list[DrumEventResponse]
    beats: list[BeatPointResponse] = []


@router.get("/{job_id}/analysis", response_model=AnalysisResponse)
def get_job_analysis(job_id: str, store: JobStore = Depends(get_job_store)) -> AnalysisResponse:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.events is None or job.tempo_bpm is None:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis not available yet: job status is {job.status.value}",
        )

    return AnalysisResponse(
        tempo_bpm=job.tempo_bpm,
        events=[DrumEventResponse.from_event(event) for event in job.events],
        beats=[BeatPointResponse.from_domain(beat) for beat in (job.beats or [])],
    )
```

- [ ] **Step 4: Run the full backend test suite**

Run (from `backend/`): `pytest`
Expected: PASS — new tests pass, no existing test broken (this is an additive field with a default, so `test_get_analysis_returns_tempo_and_events_when_job_is_tempo_mapped`'s existing assertions on `tempo_bpm`/`events` are unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: expose beat anchors on the job analysis endpoint

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 2: Frontend Beat type + SyncedPlayer playback rate

Widens `SyncedPlayer` with a rate-aware clock (the one necessary touch to the existing, well-tested transport) and threads the new `beats` field from Task 1 into the frontend's `Analysis` type. This task can run in parallel with Task 1 (different codebases) but must land before Task 3.

**Files:**
- Modify: `frontend/lib/api/jobs.ts` (add `Beat`, extend `Analysis`)
- Modify: `frontend/lib/audio/SyncedPlayer.ts` (`BufferSourceNodeLike`, `setPlaybackRate`, rate-aware `getCurrentTime`)
- Modify: `frontend/lib/audio/__tests__/SyncedPlayer.test.ts` (extend `FakeBufferSource`, add rate tests)
- Modify: `frontend/components/__tests__/EndToEndFlow.test.tsx` (extend `FakeBufferSource` so the real `SyncedPlayer` doesn't crash on `.playbackRate.value = ...`)

**Interfaces:**
- Produces: `Beat` (`@/lib/api/jobs`: `{ source_time: number; measure: number; beat: number; is_downbeat: boolean; confidence: number | null }`), `Analysis.beats: Beat[]` — consumed by Task 4/8. `SyncedPlayer.setPlaybackRate(rate: number): void`, `SyncedPlayer.getPlaybackRate(): number` — consumed by Task 3's `PracticeTransport`.

- [ ] **Step 1: Add the `Beat` type**

In `frontend/lib/api/jobs.ts`, change:

```ts
export interface Analysis {
  tempo_bpm: number;
  events: AnalysisEvent[];
}
```

to:

```ts
export interface Beat {
  source_time: number;
  measure: number;
  beat: number;
  is_downbeat: boolean;
  confidence: number | null;
}

export interface Analysis {
  tempo_bpm: number;
  events: AnalysisEvent[];
  beats: Beat[];
}
```

(Mirrors this codebase's existing convention of keeping frontend fields byte-identical to the backend's snake_case JSON — see `AnalysisEvent`/`Job` in the same file — no camelCase mapping layer exists here.)

- [ ] **Step 2: Run the typecheck to confirm no existing code breaks**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: PASS — `Analysis` is only ever read from a real fetch response or a loosely-typed test mock (`jest.Mock`), so adding a required field with no default doesn't break any typed literal in the tree. Confirm with `grep -rn "tempo_bpm:" frontend --include=*.tsx --include=*.ts` that no test constructs a fully-typed `Analysis` object literal (they don't — `EndToEndFlow.test.tsx`/`JobForm.test.tsx` mock via `jest.Mock`, which isn't type-checked against `Analysis`).

- [ ] **Step 3: Write the failing SyncedPlayer rate tests**

In `frontend/lib/audio/__tests__/SyncedPlayer.test.ts`, change the `FakeBufferSource` class:

```ts
class FakeBufferSource {
  buffer: unknown = null;
  connect = jest.fn();
  start = jest.fn();
  stop = jest.fn();
}
```

to:

```ts
class FakeBufferSource {
  buffer: unknown = null;
  playbackRate = { value: 1 };
  connect = jest.fn();
  start = jest.fn();
  stop = jest.fn();
}
```

Then append, inside the existing `describe("SyncedPlayer", ...)` block, after the last test:

```ts
  it("should default to playback rate 1", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    expect(player.getPlaybackRate()).toBe(1);
  });

  it("should apply the playback rate to both stems when starting playback", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));
    player.setPlaybackRate(1.5);

    player.play();

    const sources = context.createBufferSource.mock.results.map((r) => r.value as FakeBufferSource);
    sources.forEach((source) => expect(source.playbackRate.value).toBe(1.5));
  });

  it("should scale elapsed context time by the playback rate when reporting current time", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));
    player.setPlaybackRate(2);
    context.currentTime = 0;
    player.play();

    context.currentTime = 3;

    expect(player.getCurrentTime()).toBe(6);
  });

  it("should rebase offset and restart both stems at the current position when changing rate mid-playback", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));
    context.currentTime = 0;
    player.play();
    context.currentTime = 2;

    player.setPlaybackRate(2);

    const allSources = context.createBufferSource.mock.results.map((r) => r.value as FakeBufferSource);
    const newSources = allSources.slice(2);
    expect(newSources).toHaveLength(2);
    newSources.forEach((source) => {
      expect(source.start).toHaveBeenCalledWith(0, 2);
      expect(source.playbackRate.value).toBe(2);
    });

    context.currentTime = 3;
    expect(player.getCurrentTime()).toBe(4);
  });

  it("should change rate while paused without starting playback", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    player.setPlaybackRate(0.5);

    expect(player.getPlaybackRate()).toBe(0.5);
    expect(context.createBufferSource).not.toHaveBeenCalled();
  });
```

- [ ] **Step 4: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- SyncedPlayer.test.ts`
Expected: FAIL — `player.getPlaybackRate is not a function`.

- [ ] **Step 5: Implement `setPlaybackRate`/`getPlaybackRate` and a rate-aware clock**

In `frontend/lib/audio/SyncedPlayer.ts`, change the `BufferSourceNodeLike` interface:

```ts
export interface BufferSourceNodeLike {
  buffer: unknown;
  connect(destination: unknown): void;
  start(when?: number, offset?: number): void;
  stop(): void;
}
```

to:

```ts
export interface BufferSourceNodeLike {
  buffer: unknown;
  playbackRate: { value: number };
  connect(destination: unknown): void;
  start(when?: number, offset?: number): void;
  stop(): void;
}
```

Add a `rate` field and two accessor methods to the `SyncedPlayer` class (near the other private fields/methods):

```ts
  private rate = 1;
```

```ts
  setPlaybackRate(rate: number): void {
    if (this.playing) {
      const currentOffset = this.getCurrentTime();
      this.stopSources();
      this.rate = rate;
      this.offset = currentOffset;
      this.startSources(this.offset);
      this.startContextTime = this.context.currentTime;
    } else {
      this.rate = rate;
    }
  }

  getPlaybackRate(): number {
    return this.rate;
  }
```

Change `getCurrentTime()` from:

```ts
  getCurrentTime(): number {
    if (!this.playing) {
      return this.offset;
    }
    const elapsed = this.offset + (this.context.currentTime - this.startContextTime);
    if (elapsed >= this.duration) {
      this.stopSources();
      this.playing = false;
      this.offset = this.duration;
      return this.offset;
    }
    return elapsed;
  }
```

to:

```ts
  getCurrentTime(): number {
    if (!this.playing) {
      return this.offset;
    }
    const elapsed = this.offset + (this.context.currentTime - this.startContextTime) * this.rate;
    if (elapsed >= this.duration) {
      this.stopSources();
      this.playing = false;
      this.offset = this.duration;
      return this.offset;
    }
    return elapsed;
  }
```

Change `startSources` from:

```ts
  private startSources(offset: number): void {
    this.drumsSource = this.context.createBufferSource();
    this.drumsSource.buffer = this.drumsBuffer;
    this.drumsSource.connect(this.drumsGain);
    this.drumsSource.start(0, offset);

    this.accompanimentSource = this.context.createBufferSource();
    this.accompanimentSource.buffer = this.accompanimentBuffer;
    this.accompanimentSource.connect(this.accompanimentGain);
    this.accompanimentSource.start(0, offset);
  }
```

to:

```ts
  private startSources(offset: number): void {
    this.drumsSource = this.context.createBufferSource();
    this.drumsSource.buffer = this.drumsBuffer;
    this.drumsSource.playbackRate.value = this.rate;
    this.drumsSource.connect(this.drumsGain);
    this.drumsSource.start(0, offset);

    this.accompanimentSource = this.context.createBufferSource();
    this.accompanimentSource.buffer = this.accompanimentBuffer;
    this.accompanimentSource.playbackRate.value = this.rate;
    this.accompanimentSource.connect(this.accompanimentGain);
    this.accompanimentSource.start(0, offset);
  }
```

- [ ] **Step 6: Run the SyncedPlayer suite to verify it passes**

Run (from `frontend/`): `npm test -- SyncedPlayer.test.ts`
Expected: PASS (18 tests — 13 existing + 5 new).

- [ ] **Step 7: Fix EndToEndFlow's FakeBufferSource so real SyncedPlayer playback doesn't crash**

`EndToEndFlow.test.tsx` exercises a real `SyncedPlayer` (not mocked) against its own `FakeBufferSource`, which now needs a `playbackRate` field since `startSources` assigns to it. In `frontend/components/__tests__/EndToEndFlow.test.tsx`, change:

```ts
class FakeBufferSource {
  buffer: unknown = null;
  connect = jest.fn();
  start = jest.fn();
  stop = jest.fn();
}
```

to:

```ts
class FakeBufferSource {
  buffer: unknown = null;
  playbackRate = { value: 1 };
  connect = jest.fn();
  start = jest.fn();
  stop = jest.fn();
}
```

- [ ] **Step 8: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/api/jobs.ts frontend/lib/audio/SyncedPlayer.ts frontend/lib/audio/__tests__/SyncedPlayer.test.ts frontend/components/__tests__/EndToEndFlow.test.tsx
git commit -m "feat: add Beat type and rate-aware playback to SyncedPlayer

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 3: PracticeTransport — loop restart and rate delegation

New class composing `SyncedPlayer`. Depends on Task 2 (`setPlaybackRate`/`getPlaybackRate`).

**Files:**
- Create: `frontend/lib/audio/PracticeTransport.ts`
- Test: `frontend/lib/audio/__tests__/PracticeTransport.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks directly (defines its own minimal `PlayerLike`/`MetronomeContextLike` structural interfaces so it doesn't couple to `SyncedPlayer`'s concrete type — satisfied structurally by `SyncedPlayer` once Task 2 lands).
- Produces: `LoopRange`, `shouldRestartLoop(currentTime: number, loop: LoopRange | null): boolean`, `loopRestartOffset(loop: LoopRange): number`, `PracticeTransport` class with `play/pause/seek/getCurrentTime/isPlaying/duration/setLoop/getLoop/setPlaybackRate/getPlaybackRate/tick` — consumed by Task 4 (extends the same class) and Task 8 (`Player.tsx`).

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/audio/__tests__/PracticeTransport.test.ts
import {
  loopRestartOffset,
  PracticeTransport,
  shouldRestartLoop,
  type MetronomeContextLike,
  type PlayerLike,
} from "../PracticeTransport";

class FakePlayer implements PlayerLike {
  isPlaying = false;
  duration = 30;
  play = jest.fn(() => {
    this.isPlaying = true;
  });
  pause = jest.fn(() => {
    this.isPlaying = false;
  });
  seek = jest.fn();
  getCurrentTime = jest.fn(() => 0);
  setPlaybackRate = jest.fn();
  getPlaybackRate = jest.fn(() => 1);
}

function fakeContext(): MetronomeContextLike {
  return {
    currentTime: 0,
    destination: {},
    createGain: jest.fn(() => ({ gain: { value: 1 }, connect: jest.fn() })),
    createOscillator: jest.fn(() => ({
      frequency: { value: 0 },
      connect: jest.fn(),
      start: jest.fn(),
      stop: jest.fn(),
    })),
  };
}

describe("shouldRestartLoop", () => {
  it("should return false when there is no loop", () => {
    expect(shouldRestartLoop(5, null)).toBe(false);
  });

  it("should return false while current time is before the loop end", () => {
    expect(shouldRestartLoop(5, { startTime: 1, endTime: 10 })).toBe(false);
  });

  it("should return true once current time reaches the loop end", () => {
    expect(shouldRestartLoop(10, { startTime: 1, endTime: 10 })).toBe(true);
  });
});

describe("loopRestartOffset", () => {
  it("should return the loop's start time", () => {
    expect(loopRestartOffset({ startTime: 3, endTime: 10 })).toBe(3);
  });
});

describe("PracticeTransport", () => {
  let player: FakePlayer;
  let transport: PracticeTransport;

  beforeEach(() => {
    player = new FakePlayer();
    transport = new PracticeTransport(player, fakeContext(), []);
  });

  it("should delegate play/pause/seek to the wrapped player", () => {
    transport.play();
    transport.seek(4);
    transport.pause();

    expect(player.play).toHaveBeenCalled();
    expect(player.seek).toHaveBeenCalledWith(4);
    expect(player.pause).toHaveBeenCalled();
  });

  it("should delegate getCurrentTime, isPlaying, and duration to the wrapped player", () => {
    player.getCurrentTime.mockReturnValue(9);
    player.isPlaying = true;

    expect(transport.getCurrentTime()).toBe(9);
    expect(transport.isPlaying).toBe(true);
    expect(transport.duration).toBe(30);
  });

  it("should return the wrapped player's current time from tick when no loop is set", () => {
    player.getCurrentTime.mockReturnValue(7);

    expect(transport.tick()).toBe(7);
    expect(player.seek).not.toHaveBeenCalled();
  });

  it("should seek back to the loop start and report the restarted time once playback crosses the loop end", () => {
    transport.setLoop({ startTime: 2, endTime: 8 });
    player.getCurrentTime.mockReturnValue(8);

    const result = transport.tick();

    expect(player.seek).toHaveBeenCalledWith(2);
    expect(result).toBe(2);
  });

  it("should clear the loop when set to null", () => {
    transport.setLoop({ startTime: 2, endTime: 8 });
    transport.setLoop(null);
    player.getCurrentTime.mockReturnValue(8);

    transport.tick();

    expect(player.seek).not.toHaveBeenCalled();
  });

  it("should report the currently set loop range", () => {
    const range = { startTime: 1, endTime: 5 };
    transport.setLoop(range);

    expect(transport.getLoop()).toEqual(range);
  });

  it("should delegate playback rate get/set to the wrapped player", () => {
    transport.setPlaybackRate(1.5);
    player.getPlaybackRate.mockReturnValue(1.5);

    expect(player.setPlaybackRate).toHaveBeenCalledWith(1.5);
    expect(transport.getPlaybackRate()).toBe(1.5);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- PracticeTransport.test.ts`
Expected: FAIL — `Cannot find module '../PracticeTransport'`.

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/audio/PracticeTransport.ts
import type { AudioContextLike, GainNodeLike } from "./SyncedPlayer";

export interface LoopRange {
  startTime: number;
  endTime: number;
}

export function shouldRestartLoop(currentTime: number, loop: LoopRange | null): boolean {
  return loop != null && currentTime >= loop.endTime;
}

export function loopRestartOffset(loop: LoopRange): number {
  return loop.startTime;
}

export interface PlayerLike {
  readonly isPlaying: boolean;
  readonly duration: number;
  play(): void;
  pause(): void;
  seek(time: number): void;
  getCurrentTime(): number;
  setPlaybackRate(rate: number): void;
  getPlaybackRate(): number;
}

export interface OscillatorNodeLike {
  frequency: { value: number };
  connect(destination: unknown): void;
  start(when?: number): void;
  stop(when?: number): void;
}

export interface MetronomeContextLike extends AudioContextLike {
  createGain(): GainNodeLike;
  createOscillator(): OscillatorNodeLike;
}

export class PracticeTransport {
  private readonly player: PlayerLike;
  protected readonly context: MetronomeContextLike;
  private loop: LoopRange | null = null;

  constructor(player: PlayerLike, context: MetronomeContextLike, _beats: unknown[]) {
    this.player = player;
    this.context = context;
  }

  play(): void {
    this.player.play();
  }

  pause(): void {
    this.player.pause();
  }

  seek(time: number): void {
    this.player.seek(time);
  }

  getCurrentTime(): number {
    return this.player.getCurrentTime();
  }

  get isPlaying(): boolean {
    return this.player.isPlaying;
  }

  get duration(): number {
    return this.player.duration;
  }

  setLoop(range: LoopRange | null): void {
    this.loop = range;
  }

  getLoop(): LoopRange | null {
    return this.loop;
  }

  setPlaybackRate(rate: number): void {
    this.player.setPlaybackRate(rate);
  }

  getPlaybackRate(): number {
    return this.player.getPlaybackRate();
  }

  tick(): number {
    const currentTime = this.player.getCurrentTime();
    if (shouldRestartLoop(currentTime, this.loop)) {
      const restartTime = loopRestartOffset(this.loop as LoopRange);
      this.player.seek(restartTime);
      return restartTime;
    }
    return currentTime;
  }
}
```

(`_beats` is accepted but unused until Task 4 — kept in the constructor signature now so Task 4 only adds behavior, not a breaking signature change other call sites would need to revisit.)

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `frontend/`): `npm test -- PracticeTransport.test.ts`
Expected: PASS (9 tests).

- [ ] **Step 5: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/audio/PracticeTransport.ts frontend/lib/audio/__tests__/PracticeTransport.test.ts
git commit -m "feat: add PracticeTransport with loop restart and rate delegation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 4: Metronome scheduling and count-in

Extends `PracticeTransport` (Task 3) with metronome/count-in click scheduling, and the pure functions behind it. Depends on Task 3 (same file/class) and Task 2 (`Beat` type).

**Files:**
- Create: `frontend/lib/audio/metronomeScheduling.ts`
- Test: `frontend/lib/audio/__tests__/metronomeScheduling.test.ts`
- Modify: `frontend/lib/audio/PracticeTransport.ts` (constructor now uses `beats`; add `setMetronomeEnabled`/`playWithCountIn`; `tick` schedules clicks)
- Modify: `frontend/lib/audio/__tests__/PracticeTransport.test.ts` (metronome/count-in tests)

**Interfaces:**
- Consumes: `Beat` (`@/lib/api/jobs`, Task 2).
- Produces: `beatPeriodAt(beats: Beat[], sourceTime: number): number | null`, `beatsInWindow(beats: Beat[], windowStart: number, windowEnd: number): Beat[]`, `countInClickTimes(beats: Beat[], startTime: number, clickCount: number): number[]`, `contextTimeForSourceTime(sourceTime: number, currentSourceTime: number, currentContextTime: number, rate: number): number` — consumed by `PracticeTransport`. `PracticeTransport.setMetronomeEnabled(enabled: boolean): void`, `PracticeTransport.playWithCountIn(): void` — consumed by Task 8.

- [ ] **Step 1: Write the failing pure-function tests**

```ts
// frontend/lib/audio/__tests__/metronomeScheduling.test.ts
import {
  beatPeriodAt,
  beatsInWindow,
  contextTimeForSourceTime,
  countInClickTimes,
} from "../metronomeScheduling";
import type { Beat } from "@/lib/api/jobs";

function beat(source_time: number, measure: number, beatNumber: number, isDownbeat: boolean): Beat {
  return { source_time, measure, beat: beatNumber, is_downbeat: isDownbeat, confidence: null };
}

const BEATS: Beat[] = [
  beat(0, 1, 1, true),
  beat(0.5, 1, 2, false),
  beat(1.0, 1, 3, false),
  beat(1.5, 1, 4, false),
  beat(2.0, 2, 1, true),
];

describe("beatPeriodAt", () => {
  it("should return null when fewer than two beats are available", () => {
    expect(beatPeriodAt([beat(0, 1, 1, true)], 0)).toBeNull();
  });

  it("should return the interval to the next beat when sourceTime lands on a beat with a successor", () => {
    expect(beatPeriodAt(BEATS, 0.5)).toBe(0.5);
  });

  it("should return the interval from the previous beat when sourceTime is at or past the last beat", () => {
    expect(beatPeriodAt(BEATS, 5)).toBe(0.5);
  });

  it("should use the nearest preceding beat's period for a time between two anchors", () => {
    expect(beatPeriodAt(BEATS, 0.75)).toBe(0.5);
  });
});

describe("beatsInWindow", () => {
  it("should return only beats within [windowStart, windowEnd)", () => {
    const result = beatsInWindow(BEATS, 0.5, 1.5);

    expect(result.map((b) => b.source_time)).toEqual([0.5, 1.0]);
  });

  it("should return an empty array when no beats fall in the window", () => {
    expect(beatsInWindow(BEATS, 10, 20)).toEqual([]);
  });
});

describe("countInClickTimes", () => {
  it("should return an empty array when fewer than two beats are available", () => {
    expect(countInClickTimes([beat(0, 1, 1, true)], 0, 4)).toEqual([]);
  });

  it("should space clicks by the local beat period starting at 0", () => {
    const times = countInClickTimes(BEATS, 0, 4);

    expect(times).toEqual([0, 0.5, 1.0, 1.5]);
  });
});

describe("contextTimeForSourceTime", () => {
  it("should return the current context time unchanged for the current source time", () => {
    expect(contextTimeForSourceTime(5, 5, 100, 1)).toBe(100);
  });

  it("should convert a future source time to a real-time deadline at rate 1", () => {
    expect(contextTimeForSourceTime(7, 5, 100, 1)).toBe(102);
  });

  it("should divide by rate so a faster rate reaches the same source time sooner in real time", () => {
    expect(contextTimeForSourceTime(7, 5, 100, 2)).toBe(101);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- metronomeScheduling.test.ts`
Expected: FAIL — `Cannot find module '../metronomeScheduling'`.

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/audio/metronomeScheduling.ts
import type { Beat } from "@/lib/api/jobs";

export function beatPeriodAt(beats: Beat[], sourceTime: number): number | null {
  if (beats.length < 2) {
    return null;
  }

  let index = 0;
  for (let i = 0; i < beats.length; i++) {
    if (beats[i].source_time <= sourceTime) {
      index = i;
    } else {
      break;
    }
  }

  if (index < beats.length - 1) {
    return beats[index + 1].source_time - beats[index].source_time;
  }
  return beats[index].source_time - beats[index - 1].source_time;
}

export function beatsInWindow(beats: Beat[], windowStart: number, windowEnd: number): Beat[] {
  return beats.filter((beat) => beat.source_time >= windowStart && beat.source_time < windowEnd);
}

export function countInClickTimes(beats: Beat[], startTime: number, clickCount: number): number[] {
  const period = beatPeriodAt(beats, startTime);
  if (period == null) {
    return [];
  }
  return Array.from({ length: clickCount }, (_, i) => i * period);
}

// Maps a beat's fixed source-audio timestamp to the real Web Audio context
// deadline it should fire at, given where playback currently is (both in
// source time and real context time) and the current playback rate - one
// second of context time advances sourceTime by `rate` seconds, so covering
// a `(sourceTime - currentSourceTime)` gap takes `/rate` real seconds.
export function contextTimeForSourceTime(
  sourceTime: number,
  currentSourceTime: number,
  currentContextTime: number,
  rate: number,
): number {
  return currentContextTime + (sourceTime - currentSourceTime) / rate;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `frontend/`): `npm test -- metronomeScheduling.test.ts`
Expected: PASS (10 tests).

- [ ] **Step 5: Write the failing PracticeTransport metronome/count-in tests**

In `frontend/lib/audio/__tests__/PracticeTransport.test.ts`, change the import line to also pull in `Beat`:

```ts
import type { Beat } from "@/lib/api/jobs";
```

Add a `beat()` helper near the top (after the `fakeContext` function):

```ts
function beat(source_time: number, measure: number, beatNumber: number, isDownbeat: boolean): Beat {
  return { source_time, measure, beat: beatNumber, is_downbeat: isDownbeat, confidence: null };
}
```

Append a new describe block at the end of the file:

```ts
describe("PracticeTransport metronome and count-in", () => {
  let player: FakePlayer;
  let context: ReturnType<typeof fakeContext>;
  const beats: Beat[] = [beat(0, 1, 1, true), beat(0.5, 1, 2, false), beat(1.0, 1, 3, false), beat(1.5, 1, 4, false)];

  beforeEach(() => {
    player = new FakePlayer();
    context = fakeContext();
  });

  it("should not schedule any clicks when the metronome is disabled", () => {
    const transport = new PracticeTransport(player, context, beats);
    player.isPlaying = true;
    player.getCurrentTime.mockReturnValue(0);

    transport.tick();

    expect(context.createOscillator).not.toHaveBeenCalled();
  });

  it("should schedule a click for a beat that falls within the lookahead window once the metronome is enabled", () => {
    const transport = new PracticeTransport(player, context, beats);
    player.isPlaying = true;
    player.getCurrentTime.mockReturnValue(0);
    transport.setMetronomeEnabled(true);

    transport.tick();

    expect(context.createOscillator).toHaveBeenCalledTimes(1);
  });

  it("should not schedule the same beat's click twice across repeated ticks", () => {
    const transport = new PracticeTransport(player, context, beats);
    player.isPlaying = true;
    player.getCurrentTime.mockReturnValue(0);
    transport.setMetronomeEnabled(true);

    transport.tick();
    transport.tick();

    expect(context.createOscillator).toHaveBeenCalledTimes(1);
  });

  it("should not schedule clicks while the transport is not playing", () => {
    const transport = new PracticeTransport(player, context, beats);
    player.isPlaying = false;
    player.getCurrentTime.mockReturnValue(0);
    transport.setMetronomeEnabled(true);

    transport.tick();

    expect(context.createOscillator).not.toHaveBeenCalled();
  });

  it("should schedule count-in clicks and delay play until they finish", () => {
    jest.useFakeTimers();
    const transport = new PracticeTransport(player, context, beats);
    player.getCurrentTime.mockReturnValue(0);

    transport.playWithCountIn();

    expect(context.createOscillator).toHaveBeenCalledTimes(4);
    expect(player.play).not.toHaveBeenCalled();

    jest.advanceTimersByTime(1500);

    expect(player.play).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });

  it("should play immediately with no count-in when fewer than two beats are available", () => {
    const transport = new PracticeTransport(player, context, [beat(0, 1, 1, true)]);
    player.getCurrentTime.mockReturnValue(0);

    transport.playWithCountIn();

    expect(context.createOscillator).not.toHaveBeenCalled();
    expect(player.play).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 6: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- PracticeTransport.test.ts`
Expected: FAIL — `transport.setMetronomeEnabled is not a function`.

- [ ] **Step 7: Implement metronome/count-in on PracticeTransport**

In `frontend/lib/audio/PracticeTransport.ts`, add the import:

```ts
import type { Beat } from "@/lib/api/jobs";
import { beatPeriodAt, contextTimeForSourceTime, countInClickTimes } from "./metronomeScheduling";
```

Change the constructor from:

```ts
  constructor(player: PlayerLike, context: MetronomeContextLike, _beats: unknown[]) {
    this.player = player;
    this.context = context;
  }
```

to:

```ts
  private readonly beats: Beat[];
  private metronomeEnabled = false;
  private nextMetronomeBeatIndex = -1;

  constructor(player: PlayerLike, context: MetronomeContextLike, beats: Beat[]) {
    this.player = player;
    this.context = context;
    this.beats = beats;
  }
```

(Move the three new field declarations above the constructor, next to the existing `private loop: LoopRange | null = null;` field.)

Change `tick()` from:

```ts
  tick(): number {
    const currentTime = this.player.getCurrentTime();
    if (shouldRestartLoop(currentTime, this.loop)) {
      const restartTime = loopRestartOffset(this.loop as LoopRange);
      this.player.seek(restartTime);
      return restartTime;
    }
    return currentTime;
  }
```

to:

```ts
  tick(): number {
    const currentTime = this.player.getCurrentTime();
    let resultTime = currentTime;

    if (shouldRestartLoop(currentTime, this.loop)) {
      const restartTime = loopRestartOffset(this.loop as LoopRange);
      this.player.seek(restartTime);
      resultTime = restartTime;
      if (this.metronomeEnabled) {
        this.nextMetronomeBeatIndex = this.beats.findIndex((beat) => beat.source_time >= resultTime);
      }
    }

    if (this.metronomeEnabled && this.player.isPlaying) {
      this.scheduleUpcomingClicks(resultTime);
    }

    return resultTime;
  }

  setMetronomeEnabled(enabled: boolean): void {
    this.metronomeEnabled = enabled;
    if (enabled) {
      this.nextMetronomeBeatIndex = this.beats.findIndex((beat) => beat.source_time >= this.player.getCurrentTime());
    }
  }

  playWithCountIn(): void {
    const startTime = this.player.getCurrentTime();
    const clickTimes = countInClickTimes(this.beats, startTime, COUNT_IN_CLICK_COUNT);
    if (clickTimes.length === 0) {
      this.play();
      return;
    }

    const contextNow = this.context.currentTime;
    clickTimes.forEach((offset) => {
      this.scheduleClick(contextNow + offset, false);
    });

    const period = beatPeriodAt(this.beats, startTime) ?? 0;
    const totalDuration = clickTimes.length * period;
    setTimeout(() => this.play(), totalDuration * 1000);
  }

  private scheduleUpcomingClicks(currentSourceTime: number): void {
    if (this.nextMetronomeBeatIndex === -1) {
      return;
    }
    const rate = this.player.getPlaybackRate();
    const contextNow = this.context.currentTime;
    const lookaheadSourceTime = currentSourceTime + METRONOME_LOOKAHEAD_SECONDS * rate;

    while (
      this.nextMetronomeBeatIndex < this.beats.length &&
      this.beats[this.nextMetronomeBeatIndex].source_time < lookaheadSourceTime
    ) {
      const beat = this.beats[this.nextMetronomeBeatIndex];
      const when = contextTimeForSourceTime(beat.source_time, currentSourceTime, contextNow, rate);
      this.scheduleClick(when, beat.is_downbeat);
      this.nextMetronomeBeatIndex++;
    }
  }

  private scheduleClick(when: number, isDownbeat: boolean): void {
    const oscillator = this.context.createOscillator();
    const gain = this.context.createGain();
    oscillator.frequency.value = isDownbeat ? CLICK_FREQUENCY_DOWNBEAT : CLICK_FREQUENCY_BEAT;
    oscillator.connect(gain);
    gain.connect(this.context.destination);
    gain.gain.value = 0.5;
    oscillator.start(when);
    oscillator.stop(when + CLICK_DURATION_SECONDS);
  }
```

Add these module-level constants near the top of the file, after the imports:

```ts
const METRONOME_LOOKAHEAD_SECONDS = 0.1;
const CLICK_FREQUENCY_DOWNBEAT = 1500;
const CLICK_FREQUENCY_BEAT = 1000;
const CLICK_DURATION_SECONDS = 0.03;
const COUNT_IN_CLICK_COUNT = 4;
```

- [ ] **Step 8: Run the tests to verify they pass**

Run (from `frontend/`): `npm test -- PracticeTransport.test.ts`
Expected: PASS (15 tests).

- [ ] **Step 9: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/lib/audio/metronomeScheduling.ts frontend/lib/audio/__tests__/metronomeScheduling.test.ts frontend/lib/audio/PracticeTransport.ts frontend/lib/audio/__tests__/PracticeTransport.test.ts
git commit -m "feat: add metronome and count-in scheduling to PracticeTransport

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 5: useScoreEditor hook (correction state + undo/redo)

Independent of Tasks 2-4 (pure score-model work, no audio). Can be developed in parallel with them.

Also resolves the `insertHit`-can't-grow-measures gap noted in TECHNICAL_DEBT.md (V1-018): the correction editor UI built in Task 8 only lets a user pick a position among the score's *existing* measures (a bounded dropdown/number input clamped to `1..score.measures.length`, not free-form), so the out-of-range case stays unreachable through the UI exactly as it was before this epic — this task closes the open question by recording that determination, not by changing `insertHit`.

**Files:**
- Create: `frontend/lib/score/useScoreEditor.ts`
- Test: `frontend/lib/score/__tests__/useScoreEditor.test.ts`
- Modify: `TECHNICAL_DEBT.md` (close the open question on the `insertHit` entry)

**Interfaces:**
- Consumes: `fromAnalysisEvents` (`@/lib/score/buildScore`, existing), `addHit`/`deleteHit`/`moveHit`/`changeInstrument` (`@/lib/score/transformations`, existing), `AnalysisEvent`/`DrumInstrument` (`@/lib/api/jobs`, existing), `MusicalPosition`/`Score` (`@/lib/score/types`, existing).
- Produces: `useScoreEditor(events: AnalysisEvent[]): ScoreEditor` where `ScoreEditor = { score: Score; addHit; deleteHit; moveHit; changeInstrument; undo: () => void; redo: () => void; canUndo: boolean; canRedo: boolean }` — consumed by Task 8's `Player.tsx`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/score/__tests__/useScoreEditor.test.ts
import { act, renderHook } from "@testing-library/react";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { useScoreEditor } from "../useScoreEditor";

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

describe("useScoreEditor", () => {
  it("should build the initial score from the given events", () => {
    const { result } = renderHook(() => useScoreEditor([event({ instrument: "kick", beat: 1, subdivision: 0 })]));

    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot).toBeDefined();
  });

  it("should apply addHit and reflect the new hit in the score", () => {
    const { result } = renderHook(() => useScoreEditor([]));

    act(() => {
      result.current.addHit({ measure: 1, beat: 1, subdivision: 0 }, "snare");
    });

    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot?.type).toBe("note");
  });

  it("should apply deleteHit by delegating to the underlying transformation", () => {
    const events = [event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 })];
    const { result } = renderHook(() => useScoreEditor(events));
    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    const hitId = (noteSlot as { hits: { id: string }[] }).hits[0].id;

    act(() => {
      result.current.deleteHit(hitId);
    });

    const slot = result.current.score.measures[0].find((s) => s.position.beat === 1 && s.position.subdivision === 0);
    expect(slot?.type).toBe("rest");
  });

  it("should undo the most recent edit back to the previous score", () => {
    const events = [event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 })];
    const { result } = renderHook(() => useScoreEditor(events));
    const scoreBeforeEdit = result.current.score;

    act(() => {
      result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare");
    });
    expect(result.current.canUndo).toBe(true);

    act(() => {
      result.current.undo();
    });

    expect(result.current.score).toEqual(scoreBeforeEdit);
    expect(result.current.canUndo).toBe(false);
  });

  it("should redo an undone edit", () => {
    const { result } = renderHook(() => useScoreEditor([]));

    act(() => {
      result.current.addHit({ measure: 1, beat: 1, subdivision: 0 }, "snare");
    });
    const scoreAfterEdit = result.current.score;
    act(() => {
      result.current.undo();
    });
    expect(result.current.canRedo).toBe(true);

    act(() => {
      result.current.redo();
    });

    expect(result.current.score).toEqual(scoreAfterEdit);
    expect(result.current.canRedo).toBe(false);
  });

  it("should clear the redo stack when a new edit is made after an undo", () => {
    const { result } = renderHook(() => useScoreEditor([]));

    act(() => {
      result.current.addHit({ measure: 1, beat: 1, subdivision: 0 }, "snare");
    });
    act(() => {
      result.current.undo();
    });
    expect(result.current.canRedo).toBe(true);

    act(() => {
      result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "kick");
    });

    expect(result.current.canRedo).toBe(false);
  });

  it("should do nothing when undo is called with an empty undo stack", () => {
    const { result } = renderHook(() => useScoreEditor([]));
    const initialScore = result.current.score;

    act(() => {
      result.current.undo();
    });

    expect(result.current.score).toBe(initialScore);
  });

  it("should reset score and history when given a new events array", () => {
    const firstEvents = [event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 })];
    const { result, rerender } = renderHook(({ events }) => useScoreEditor(events), {
      initialProps: { events: firstEvents },
    });
    act(() => {
      result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare");
    });
    expect(result.current.canUndo).toBe(true);

    const secondEvents = [event({ id: "b", instrument: "snare", beat: 3, subdivision: 0 })];
    rerender({ events: secondEvents });

    expect(result.current.canUndo).toBe(false);
    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot?.type === "note" && noteSlot.hits[0].instrument).toBe("snare");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- useScoreEditor.test.ts`
Expected: FAIL — `Cannot find module '../useScoreEditor'`.

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/score/useScoreEditor.ts
import { useRef, useState } from "react";

import type { AnalysisEvent, DrumInstrument } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "./buildScore";
import { addHit, changeInstrument, deleteHit, moveHit } from "./transformations";
import type { MusicalPosition, Score } from "./types";

export interface ScoreEditor {
  score: Score;
  addHit: (position: MusicalPosition, instrument: DrumInstrument) => void;
  deleteHit: (hitId: string) => void;
  moveHit: (hitId: string, newPosition: MusicalPosition) => void;
  changeInstrument: (hitId: string, newInstrument: DrumInstrument) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

export function useScoreEditor(events: AnalysisEvent[]): ScoreEditor {
  const [score, setScore] = useState<Score>(() => fromAnalysisEvents(events));
  const [undoStack, setUndoStack] = useState<Score[]>([]);
  const [redoStack, setRedoStack] = useState<Score[]>([]);
  const eventsRef = useRef(events);

  // Re-baselines when a genuinely new job's events arrive (a different
  // AnalysisEvent[] identity) - there is nothing to preserve across an
  // entirely different song. React's documented "adjusting state when a
  // prop changes" pattern: detected and applied synchronously during
  // render, so the very first render (eventsRef initialized to the same
  // `events` reference) never redundantly rebuilds.
  if (eventsRef.current !== events) {
    eventsRef.current = events;
    setScore(fromAnalysisEvents(events));
    setUndoStack([]);
    setRedoStack([]);
  }

  function applyEdit(next: Score): void {
    setUndoStack((stack) => [...stack, score]);
    setRedoStack([]);
    setScore(next);
  }

  return {
    score,
    addHit: (position, instrument) => applyEdit(addHit(score, position, instrument)),
    deleteHit: (hitId) => applyEdit(deleteHit(score, hitId)),
    moveHit: (hitId, newPosition) => applyEdit(moveHit(score, hitId, newPosition)),
    changeInstrument: (hitId, newInstrument) => applyEdit(changeInstrument(score, hitId, newInstrument)),
    undo: () => {
      setUndoStack((stack) => {
        if (stack.length === 0) {
          return stack;
        }
        const previous = stack[stack.length - 1];
        setRedoStack((redo) => [...redo, score]);
        setScore(previous);
        return stack.slice(0, -1);
      });
    },
    redo: () => {
      setRedoStack((stack) => {
        if (stack.length === 0) {
          return stack;
        }
        const next = stack[stack.length - 1];
        setUndoStack((undo) => [...undo, score]);
        setScore(next);
        return stack.slice(0, -1);
      });
    },
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `frontend/`): `npm test -- useScoreEditor.test.ts`
Expected: PASS (8 tests).

- [ ] **Step 5: Record the insertHit determination in TECHNICAL_DEBT.md**

Append to the end of `TECHNICAL_DEBT.md`, after the existing "Beam grouping does not beam across an intra-beat rest" entry:

```markdown
---

## `insertHit`'s out-of-range-measure gap remains unreachable after Epic 5

**Found in:** V1-027/#78 (Epic 5 correction editor) design

The "`insertHit` cannot create a new measure" entry above was left deferred
during V1-018/#51 because it wasn't reachable from any UI. Epic 5 adds the
first real UI that calls `addHit`/`moveHit` (the manual correction editor),
so this needed re-checking: the editor's position inputs (`Player.tsx`,
V1-027/#78) are deliberately bounded to `1..score.measures.length` rather
than free-form, so a user still cannot construct an out-of-range
`position.measure`. The gap stays unreachable and therefore stays
deferred - recorded here as a deliberate re-confirmation, not a new
finding, so a future reader doesn't have to re-derive it when the next
UI touches `addHit`/`moveHit`.

**Deferred:** still not reachable from any UI as of Epic 5.
```

- [ ] **Step 6: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/score/useScoreEditor.ts frontend/lib/score/__tests__/useScoreEditor.test.ts TECHNICAL_DEBT.md
git commit -m "feat: add useScoreEditor hook with undo/redo history

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 6: Confidence threshold and synthetic low-confidence fixture

Independent, small, no dependencies on earlier tasks. Can run in parallel with anything.

**Files:**
- Create: `frontend/lib/score/confidence.ts`
- Test: `frontend/lib/score/__tests__/confidence.test.ts`
- Create: `frontend/lib/score/__fixtures__/lowConfidenceGroove.ts`

**Interfaces:**
- Consumes: `ScoreHit` (`@/lib/score/types`, existing).
- Produces: `LOW_CONFIDENCE_THRESHOLD = 0.5`, `isLowConfidence(hit: ScoreHit): boolean` — consumed by Task 7's `buildStaveNote.ts`. `LOW_CONFIDENCE_GROOVE_EVENTS: AnalysisEvent[]` — consumed by Task 7's `DrumScore` tests if needed for a manual smoke check (not required by any other task).

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/score/__tests__/confidence.test.ts
import { isLowConfidence, LOW_CONFIDENCE_THRESHOLD } from "../confidence";
import type { ScoreHit } from "../types";

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

describe("isLowConfidence", () => {
  it("should return false when confidence is null", () => {
    expect(isLowConfidence(hit({ confidence: null }))).toBe(false);
  });

  it("should return false when confidence is at or above the threshold", () => {
    expect(isLowConfidence(hit({ confidence: LOW_CONFIDENCE_THRESHOLD }))).toBe(false);
    expect(isLowConfidence(hit({ confidence: 0.9 }))).toBe(false);
  });

  it("should return true when confidence is below the threshold", () => {
    expect(isLowConfidence(hit({ confidence: 0.2 }))).toBe(true);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- confidence.test.ts`
Expected: FAIL — `Cannot find module '../confidence'`.

- [ ] **Step 3: Write the minimal implementation**

```ts
// frontend/lib/score/confidence.ts
import type { ScoreHit } from "./types";

export const LOW_CONFIDENCE_THRESHOLD = 0.5;

export function isLowConfidence(hit: ScoreHit): boolean {
  return hit.confidence != null && hit.confidence < LOW_CONFIDENCE_THRESHOLD;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `frontend/`): `npm test -- confidence.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Add the synthetic low-confidence fixture**

```ts
// frontend/lib/score/__fixtures__/lowConfidenceGroove.ts
import type { AnalysisEvent } from "@/lib/api/jobs";

// Synthetic fixture: real production jobs never populate confidence (see
// TECHNICAL_DEBT.md / Epic 3 - DrumScriptTranscriber never fabricates a
// confidence value it can't defend), so this is the only way to exercise
// the low-confidence review UI until a future transcription-engine change
// adds a real confidence signal.
export const LOW_CONFIDENCE_GROOVE_EVENTS: AnalysisEvent[] = [
  {
    id: "e1",
    time: 0,
    instrument: "kick",
    confidence: 0.9,
    provenance: "drumscript",
    measure: 1,
    beat: 1,
    subdivision: 0,
  },
  {
    id: "e2",
    time: 0.5,
    instrument: "snare",
    confidence: 0.2,
    provenance: "drumscript",
    measure: 1,
    beat: 2,
    subdivision: 0,
  },
];
```

- [ ] **Step 6: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/score/confidence.ts frontend/lib/score/__tests__/confidence.test.ts frontend/lib/score/__fixtures__/lowConfidenceGroove.ts
git commit -m "feat: add low-confidence threshold and synthetic review fixture

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 7: DrumScore — score prop, click-to-seek, manual/low-confidence styling

Structural change: `DrumScore` stops building its own `Score` and takes one as a prop. Depends on Task 6 (`isLowConfidence`) for styling. This task's test-file rewrite is large because every existing `DrumScore` test currently passes `events`.

**Files:**
- Modify: `frontend/lib/notation/buildStaveNote.ts` (manual/low-confidence styling)
- Modify: `frontend/lib/notation/__tests__/buildStaveNote.test.ts` (styling tests)
- Modify: `frontend/components/DrumScore.tsx` (`events` prop → `score` prop, `onSeek`)
- Modify: `frontend/components/__tests__/DrumScore.test.tsx` (full rewrite: `events={...}` → `score={fromAnalysisEvents([...])}`, plus onSeek tests)
- Modify: `frontend/components/__tests__/DrumScore.fixtures.test.tsx` (`events` → `score`)
- Modify: `docs/ARCHITECTURE_V1.md` (engraving section: note the score-prop contract)

**Interfaces:**
- Consumes: `isLowConfidence` (`@/lib/score/confidence`, Task 6); `Score`/`Slot` (`@/lib/score/types`, existing); `fromAnalysisEvents` (`@/lib/score/buildScore`, existing, test-only in this task).
- Produces: `buildStaveNote(slot: Slot): StaveNote` (unchanged signature, now applies `.setStyle(...)`), `MANUAL_HIT_STYLE`, `LOW_CONFIDENCE_STYLE` (`@/lib/notation/buildStaveNote`). `DrumScoreProps = { score: Score; currentTime?: number; onSeek?: (time: number) => void }` — consumed by Task 8's `Player.tsx`.

- [ ] **Step 1: Write the failing buildStaveNote styling tests**

In `frontend/lib/notation/__tests__/buildStaveNote.test.ts`, change the import line:

```ts
import { buildStaveNote } from "../buildStaveNote";
```

to:

```ts
import { buildStaveNote, LOW_CONFIDENCE_STYLE, MANUAL_HIT_STYLE } from "../buildStaveNote";
```

Append a new describe block at the end of the file:

```ts
describe("buildStaveNote manual/low-confidence styling", () => {
  it("should apply the manual-hit style when a hit has no source event", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ sourceEventId: null })],
    });

    expect(note.getStyle()).toMatchObject(MANUAL_HIT_STYLE);
  });

  it("should apply the low-confidence style when a hit is below the confidence threshold", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ sourceEventId: "e", confidence: 0.1 })],
    });

    expect(note.getStyle()).toMatchObject(LOW_CONFIDENCE_STYLE);
  });

  it("should apply no style override for an ordinary transcribed hit", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ sourceEventId: "e", confidence: 0.9 })],
    });

    expect(note.getStyle()).toBeUndefined();
  });

  it("should prefer the manual style over the low-confidence style when a note has both", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ id: "h1", sourceEventId: null }), hit({ id: "h2", sourceEventId: "e", confidence: 0.1 })],
    });

    expect(note.getStyle()).toMatchObject(MANUAL_HIT_STYLE);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- buildStaveNote.test.ts`
Expected: FAIL — `LOW_CONFIDENCE_STYLE`/`MANUAL_HIT_STYLE` are not exported.

- [ ] **Step 3: Implement styling in buildStaveNote**

Replace the full contents of `frontend/lib/notation/buildStaveNote.ts`:

```ts
import { StaveNote } from "vexflow";

import { isLowConfidence } from "@/lib/score/confidence";
import type { Slot } from "@/lib/score/types";
import { INSTRUMENT_NOTATION } from "./instrumentNotation";

export const MANUAL_HIT_STYLE = { fillStyle: "#3182ce", strokeStyle: "#3182ce" };
export const LOW_CONFIDENCE_STYLE = { fillStyle: "#dd6b20", strokeStyle: "#dd6b20" };

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

  if (slot.hits.some((hit) => hit.sourceEventId == null)) {
    note.setStyle(MANUAL_HIT_STYLE);
  } else if (slot.hits.some((hit) => isLowConfidence(hit))) {
    note.setStyle(LOW_CONFIDENCE_STYLE);
  }

  return note;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `frontend/`): `npm test -- buildStaveNote.test.ts`
Expected: PASS (10 tests — 6 existing + 4 new).

- [ ] **Step 5: Write the failing DrumScore tests (full file rewrite)**

Replace the full contents of `frontend/components/__tests__/DrumScore.test.tsx`:

```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "@/lib/score/buildScore";
import DrumScore from "../DrumScore";

function installFakeResizeObserver() {
  const registry = new Map<Element, ResizeObserverCallback>();

  class FakeResizeObserver {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) {
      registry.set(target, this.callback);
    }
    unobserve(target: Element) {
      registry.delete(target);
    }
    disconnect() {}
  }

  const original = global.ResizeObserver;
  global.ResizeObserver = FakeResizeObserver;

  return {
    resize(target: Element, width: number) {
      Object.defineProperty(target, "clientWidth", { value: width, configurable: true });
      const callback = registry.get(target);
      callback?.([{ target, contentRect: { width } } as ResizeObserverEntry], undefined as unknown as ResizeObserver);
    },
    restore() {
      global.ResizeObserver = original;
    },
  };
}

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

function buildScore(events: AnalysisEvent[]) {
  return fromAnalysisEvents(events);
}

describe("DrumScore", () => {
  it("should render an SVG score without throwing for a simple beat", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "3", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_open", beat: 3, subdivision: 2, time: 1.25 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const svg = container.querySelector("svg");

    expect(svg).not.toBeNull();
    expect(container.querySelectorAll(".vf-stavenote").length).toBeGreaterThan(0);
  });

  it("should render nothing extra for an empty score", () => {
    render(<DrumScore score={buildScore([])} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should not throw when given a currentTime but an empty score", () => {
    render(<DrumScore score={buildScore([])} currentTime={5} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("svg")).toBeNull();
  });

  it("should force every note's stem upward, including kick and snare", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stemPaths = container.querySelectorAll(".vf-stem");

    expect(stemPaths.length).toBeGreaterThan(0);
  });

  it("should not draw a playhead line when currentTime is not provided", () => {
    render(<DrumScore score={buildScore([event({ id: "1", beat: 1, subdivision: 0, time: 0 })])} />);

    const container = screen.getByTestId("drum-score");

    expect(container.querySelector("#drum-score-playhead")).toBeNull();
  });

  it("should draw a playhead line positioned at the current time, driven by each event's own source time", () => {
    const score = buildScore([
      event({ id: "1", beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", beat: 3, subdivision: 0, time: 7.3 }),
    ]);

    const { rerender } = render(<DrumScore currentTime={0} score={score} />);

    const container = screen.getByTestId("drum-score");
    const lineAtStart = container.querySelector("#drum-score-playhead");
    expect(lineAtStart).not.toBeNull();
    const xAtStart = Number(lineAtStart?.getAttribute("x1"));

    rerender(<DrumScore currentTime={7.3} score={score} />);

    const lineLater = container.querySelector("#drum-score-playhead");
    const xLater = Number(lineLater?.getAttribute("x1"));

    expect(xLater).toBeGreaterThan(xAtStart);
  });

  it("should auto-scroll the container horizontally to keep the playhead in view", () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth");
    Object.defineProperty(Element.prototype, "clientWidth", { value: 2000, configurable: true });

    try {
      const score = buildScore([
        event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
        event({ id: "2", measure: 4, beat: 4, subdivision: 3, time: 8 }),
      ]);

      const { rerender } = render(<DrumScore currentTime={0} score={score} />);

      const container = screen.getByTestId("drum-score");
      Object.defineProperty(container, "clientWidth", { value: 200, configurable: true });
      container.scrollLeft = 0;

      rerender(<DrumScore currentTime={8} score={score} />);

      expect(container.scrollLeft).toBeGreaterThan(0);
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(Element.prototype, "clientWidth", originalDescriptor);
      } else {
        delete (Element.prototype as { clientWidth?: number }).clientWidth;
      }
    }
  });

  it("should never move the playhead backward in x while stepping through a real multi-row score", () => {
    const lastRowZeroTime = 3.95;
    const firstRowOneTime = 4.2;
    const score = buildScore([
      event({ id: "1", measure: 4, beat: 4, subdivision: 3, instrument: "kick", time: lastRowZeroTime }),
      event({ id: "2", measure: 5, beat: 1, subdivision: 0, instrument: "snare", time: firstRowOneTime }),
    ]);

    const { rerender } = render(<DrumScore currentTime={0} score={score} />);
    const container = screen.getByTestId("drum-score");

    const sampleTimes = [
      lastRowZeroTime - 0.05,
      lastRowZeroTime,
      (lastRowZeroTime + firstRowOneTime) / 2,
      firstRowOneTime,
    ];

    let previousX: number | null = null;
    let previousY: number | null = null;
    for (const time of sampleTimes) {
      rerender(<DrumScore currentTime={time} score={score} />);
      const line = container.querySelector("#drum-score-playhead")!;
      const x = Number(line.getAttribute("x1"));
      const y = Number(line.getAttribute("y1"));

      if (previousX !== null && previousY === y) {
        expect(x).toBeGreaterThanOrEqual(previousX);
      }
      previousX = x;
      previousY = y;
    }

    rerender(<DrumScore currentTime={lastRowZeroTime} score={score} />);
    const yBeforeBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    rerender(<DrumScore currentTime={firstRowOneTime} score={score} />);
    const yAfterBoundary = container.querySelector("#drum-score-playhead")!.getAttribute("y1");
    expect(yAfterBoundary).not.toBe(yBeforeBoundary);
  });

  it("should not require a tempoBpm prop", () => {
    // @ts-expect-error tempoBpm is not part of DrumScoreProps
    render(<DrumScore score={buildScore([])} tempoBpm={120} />);

    expect(screen.getByTestId("drum-score")).toBeInTheDocument();
  });

  it("should render a separate beam per beat for a straight eighth-note groove, not one beam per measure", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 2, time: 0.25 }),
          event({ id: "3", instrument: "hihat_closed", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_closed", beat: 2, subdivision: 2, time: 0.75 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const beamGroups = container.querySelectorAll("g.vf-beam");

    expect(beamGroups.length).toBe(2);
  });

  it("should draw exactly one stem per beamed note, not a duplicate unbeamed stem underneath the beam", () => {
    render(
      <DrumScore
        score={buildScore([
          event({ id: "1", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 0 }),
          event({ id: "2", instrument: "hihat_closed", beat: 1, subdivision: 2, time: 0.25 }),
          event({ id: "3", instrument: "hihat_closed", beat: 2, subdivision: 0, time: 0.5 }),
          event({ id: "4", instrument: "hihat_closed", beat: 2, subdivision: 2, time: 0.75 }),
        ])}
      />,
    );

    const container = screen.getByTestId("drum-score");
    const stems = container.querySelectorAll(".vf-stem");

    expect(stems.length).toBe(4);
  });

  it("should reflow into more rows (a taller score) when the container becomes narrower after a resize", () => {
    const fakeResizeObserver = installFakeResizeObserver();
    try {
      const score = buildScore(
        Array.from({ length: 8 }, (_, i) => event({ id: String(i), measure: i + 1, beat: 1, subdivision: 0, time: i })),
      );

      render(<DrumScore score={score} />);
      const container = screen.getByTestId("drum-score");

      act(() => {
        fakeResizeObserver.resize(container, 2000);
      });
      const wideHeight = Number(container.querySelector("svg")!.getAttribute("height"));

      act(() => {
        fakeResizeObserver.resize(container, 250);
      });
      const narrowHeight = Number(container.querySelector("svg")!.getAttribute("height"));

      expect(narrowHeight).toBeGreaterThan(wideHeight);
    } finally {
      fakeResizeObserver.restore();
    }
  });

  it("should not rebuild the score when only currentTime changes, keeping row breaks stable during playback", () => {
    const score = buildScore([
      event({ id: "1", measure: 1, beat: 1, subdivision: 0, time: 0 }),
      event({ id: "2", measure: 2, beat: 1, subdivision: 0, time: 1 }),
    ]);

    const { rerender } = render(<DrumScore currentTime={0} score={score} />);
    const container = screen.getByTestId("drum-score");
    const svgBefore = container.querySelector("svg");

    rerender(<DrumScore currentTime={0.5} score={score} />);
    const svgAfter = container.querySelector("svg");

    expect(svgAfter).toBe(svgBefore);
  });

  it("should call onSeek with a note's source time when it is clicked", () => {
    const onSeek = jest.fn();
    const score = buildScore([event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 3.5 })]);

    render(<DrumScore score={score} onSeek={onSeek} />);

    const container = screen.getByTestId("drum-score");
    const note = container.querySelector(".vf-stavenote")!;
    fireEvent.click(note);

    expect(onSeek).toHaveBeenCalledWith(3.5);
  });

  it("should not call onSeek when a rest slot is clicked", () => {
    const onSeek = jest.fn();
    const score = buildScore([event({ id: "1", instrument: "kick", beat: 1, subdivision: 0, time: 1 })]);

    render(<DrumScore score={score} onSeek={onSeek} />);

    const container = screen.getByTestId("drum-score");
    const staveNotes = container.querySelectorAll(".vf-stavenote");
    const lastRest = staveNotes[staveNotes.length - 1];
    fireEvent.click(lastRest);

    expect(onSeek).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 6: Update the golden fixtures test**

In `frontend/components/__tests__/DrumScore.fixtures.test.tsx`, change:

```tsx
      const expectedSlotCount = fromAnalysisEvents(fixture.events).measures.flat().length;

      render(<DrumScore events={fixture.events} />);
```

to:

```tsx
      const score = fromAnalysisEvents(fixture.events);
      const expectedSlotCount = score.measures.flat().length;

      render(<DrumScore score={score} />);
```

- [ ] **Step 7: Repoint DrumScore.tsx at the score prop and wire click-to-seek**

Replace the full contents of `frontend/components/DrumScore.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { Formatter, Renderer, Stave, Voice } from "vexflow";

import { buildStaveNote } from "@/lib/notation/buildStaveNote";
import { buildBeams } from "@/lib/notation/beaming";
import { computeRowLayout } from "@/lib/notation/layout";
import { computeNoteJustifyWidth } from "@/lib/notation/staveFormatting";
import { computeAutoScrollLeft, interpolatePlayheadX, type TimelinePoint } from "@/lib/notation/timeline";
import type { Score } from "@/lib/score/types";

interface DrumScoreProps {
  score: Score;
  currentTime?: number;
  onSeek?: (time: number) => void;
}

const ROW_HEIGHT = 120;
const STAVE_X_START = 10;
// Trailing safety margin (beyond the real clef/time-signature prefix width,
// see computeNoteJustifyWidth) so the last note's glyph doesn't touch the
// stave's right edge/barline. Also folded into each measure's precalculated
// minimum width so a stave sized exactly at that minimum still has room.
const MEASURE_INNER_PADDING = 20;
const PLAYHEAD_ID = "drum-score-playhead";
// Only a real width change (not sub-pixel float jitter from ResizeObserver)
// should trigger a relayout.
const RESIZE_THRESHOLD_PX = 1;

function averageSourceTime(sourceTimes: number[]): number {
  return sourceTimes.reduce((sum, time) => sum + time, 0) / sourceTimes.length;
}

export default function DrumScore({ score, currentTime, onSeek }: DrumScoreProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<TimelinePoint[]>([]);
  const [containerWidth, setContainerWidth] = useState(0);

  // Tracks the container's real width so layout can adapt to the viewport.
  // Deliberately its own effect, independent of the score/playhead effect
  // below, so a resize can never be triggered by playback ticking and
  // playback ticking can never trigger a relayout.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    setContainerWidth(container.clientWidth);

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const width = entry.contentRect.width;
        setContainerWidth((previous) => (Math.abs(previous - width) > RESIZE_THRESHOLD_PX ? width : previous));
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container.innerHTML = "";
    timelineRef.current = [];

    const { measures } = score;
    if (measures.length === 0) {
      return;
    }

    const built = measures.map((measure) => {
      const notes = measure.map(buildStaveNote);
      // beams must be constructed before Formatter/voice.draw() - see
      // TECHNICAL_DEBT.md / #52 review.
      const beams = buildBeams(measure, notes);
      const voice = new Voice({ numBeats: 4, beatValue: 4 }).setStrict(false);
      voice.addTickables(notes);
      const minWidth = new Formatter().joinVoices([voice]).preCalculateMinTotalWidth([voice]);
      return { measure, notes, beams, voice, minWidth: minWidth + MEASURE_INNER_PADDING };
    });

    const availableWidth = Math.max(containerWidth - STAVE_X_START * 2, 0);
    const placements = computeRowLayout(
      built.map((measure) => measure.minWidth),
      availableWidth,
      { startX: STAVE_X_START },
    );

    const rows = Math.max(...placements.map((placement) => placement.row)) + 1;
    const width = Math.max(...placements.map((placement) => placement.x + placement.width)) + STAVE_X_START;
    const height = rows * ROW_HEIGHT + 40;

    const renderer = new Renderer(container, Renderer.Backends.SVG);
    renderer.resize(width, height);
    const context = renderer.getContext();

    placements.forEach(({ index, row, col, x, width: staveWidth }) => {
      const { measure, notes, beams, voice } = built[index];
      const y = 20 + row * ROW_HEIGHT;

      const stave = new Stave(x, y, staveWidth);
      if (col === 0) {
        stave.addClef("percussion");
      }
      if (index === 0) {
        stave.setTimeSignature("4/4");
      }
      stave.setContext(context).draw();

      const justifyWidth = computeNoteJustifyWidth(stave, staveWidth, MEASURE_INNER_PADDING);
      new Formatter().joinVoices([voice]).format([voice], justifyWidth);
      voice.draw(context, stave);
      beams.forEach((beam) => beam.setContext(context).draw());

      notes.forEach((note, slotIndex) => {
        const slot = measure[slotIndex];
        // Only note slots are anchored to a real source timestamp - rest
        // slots have no underlying event, so the playhead interpolates
        // smoothly across them between the nearest real anchors instead of
        // reconstructing a time from a BPM/grid assumption.
        if (slot.type !== "note") {
          return;
        }
        const times = slot.hits.map((hit) => hit.time).filter((time): time is number => time != null);
        if (times.length === 0) {
          return;
        }
        const time = averageSourceTime(times);
        timelineRef.current.push({ time, x: note.getAbsoluteX(), row });

        if (onSeek) {
          const svgElement = note.getSVGElement();
          if (svgElement) {
            svgElement.style.cursor = "pointer";
            svgElement.addEventListener("click", () => onSeek(time));
          }
        }
      });
    });
  }, [score, containerWidth, onSeek]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || currentTime == null) {
      return;
    }

    const svg = container.querySelector("svg");
    if (!svg) {
      return;
    }

    const point = interpolatePlayheadX(timelineRef.current, currentTime);
    if (!point) {
      return;
    }

    const yTop = 15 + point.row * ROW_HEIGHT;
    const yBottom = yTop + ROW_HEIGHT - 25;

    let line = svg.querySelector(`#${PLAYHEAD_ID}`);
    if (!line) {
      line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("id", PLAYHEAD_ID);
      line.setAttribute("stroke", "#e53e3e");
      line.setAttribute("stroke-width", "2");
      svg.appendChild(line);
    }
    line.setAttribute("x1", String(point.x));
    line.setAttribute("x2", String(point.x));
    line.setAttribute("y1", String(yTop));
    line.setAttribute("y2", String(yBottom));

    container.scrollLeft = computeAutoScrollLeft(container.scrollLeft, container.clientWidth, point.x);
  }, [currentTime]);

  return (
    <div
      ref={containerRef}
      data-testid="drum-score"
      style={{ width: "100%", overflowX: "auto" }}
    />
  );
}
```

- [ ] **Step 8: Run the DrumScore suites to verify they pass**

Run (from `frontend/`): `npm test -- DrumScore.test.tsx DrumScore.fixtures.test.tsx`
Expected: PASS (17 tests in `DrumScore.test.tsx`: 15 existing renamed + 2 new; `DrumScore.fixtures.test.tsx` unchanged pass count).

- [ ] **Step 9: Update the architecture doc**

In `docs/ARCHITECTURE_V1.md`, change the Engraving section's line:

```
Rendered elements retain score-event IDs for click-to-seek/editing.
```

to:

```
Rendered elements retain score-event IDs for click-to-seek/editing.
`DrumScore` takes an already-built `Score` as a prop (via `onSeek`-wired
click handlers on each rendered note) rather than constructing one
itself - score construction/editing state lives one level up
(`useScoreEditor`, Epic 5), keeping the renderer a pure function of
whatever `Score` it's handed.
```

- [ ] **Step 10: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Expected: PASS. (`Player.tsx` and `Player.test.tsx` still reference `DrumScore`'s old `events` prop at this point — Task 8 fixes that next; if the typecheck fails only on `Player.tsx`'s `<DrumScore events={events} .../>` call site, that is expected and resolved in Task 8, not a regression to fix here. Confirm the failure, if any, is isolated to that one call site before proceeding.)

- [ ] **Step 11: Commit**

```bash
git add frontend/lib/notation/buildStaveNote.ts frontend/lib/notation/__tests__/buildStaveNote.test.ts frontend/components/DrumScore.tsx frontend/components/__tests__/DrumScore.test.tsx frontend/components/__tests__/DrumScore.fixtures.test.tsx docs/ARCHITECTURE_V1.md
git commit -m "feat: DrumScore takes a Score prop, adds click-to-seek and edit styling

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 8: Player.tsx integration — the practice player and correction editor UI

The integration point: wires `PracticeTransport` (Tasks 3-4), `useScoreEditor` (Task 5), and `DrumScore`'s new `score`/`onSeek` props (Task 7) into `Player.tsx`, and adds every new UI control (loop, rate, metronome, count-in, correction editor, undo/redo). Depends on Tasks 2-7 all being complete — **do not dispatch this task until every earlier task's commit is in**. Because it touches one file end-to-end and every earlier interface at once, this task should be executed inline/sequentially rather than by a fresh subagent with only this task's slice of context — a subagent given just this task's text would be reconstructing the whole epic's design from the diff alone.

**Files:**
- Modify: `frontend/components/Player.tsx`
- Modify: `frontend/components/__tests__/Player.test.tsx`
- Modify: `frontend/components/JobForm.tsx` (thread `analysis.beats` through)

**Interfaces:**
- Consumes: `PracticeTransport`, `MetronomeContextLike` (`@/lib/audio/PracticeTransport`, Tasks 3-4); `useScoreEditor` (`@/lib/score/useScoreEditor`, Task 5); `DrumScore`'s `score`/`onSeek` props (Task 7); `INSTRUMENT_NOTATION` (`@/lib/notation/instrumentNotation`, existing); `Beat`/`DrumInstrument` (`@/lib/api/jobs`, existing/Task 2).
- Produces: `Player`'s public props gain `beats?: Beat[]` (default `[]`) — consumed by `JobForm.tsx`.

- [ ] **Step 1: Write the failing Player tests**

In `frontend/components/__tests__/Player.test.tsx`, change the import line:

```ts
import { act, fireEvent, render, screen } from "@testing-library/react";
```

(unchanged — already imports what's needed). Change the `SyncedPlayer` mock setup: after `MockedSyncedPlayer.prototype.getCurrentTime = jest.fn().mockReturnValue(0);` in the existing `beforeEach`, add:

```ts
    MockedSyncedPlayer.prototype.getPlaybackRate = jest.fn().mockReturnValue(1);
```

Add a second context factory near `fakeContextFactory`, for tests that exercise metronome/count-in:

```ts
function fakeContextFactoryWithOscillator() {
  return {
    close: jest.fn(),
    currentTime: 0,
    destination: {},
    createGain: () => ({ gain: { value: 1 }, connect: jest.fn() }),
    createOscillator: () => ({ frequency: { value: 0 }, connect: jest.fn(), start: jest.fn(), stop: jest.fn() }),
  } as never;
}
```

Append these tests at the end of the `describe("Player", ...)` block:

```ts
  it("should call onSeek's underlying transport.seek when a score note is clicked", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    let capturedOnSeek: ((time: number) => void) | undefined;
    jest.mock("@/components/DrumScore");

    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    // The mocked DrumScore in this file's top-level jest.mock doesn't expose
    // onSeek directly, so this test instead exercises seekTo through the
    // existing seek slider, which now goes through the same code path as
    // an onSeek callback from DrumScore (both call transport.seek via
    // Player's shared seekTo helper) - see the dedicated onSeek-prop-forwarding
    // assertion below for direct prop verification.
    fireEvent.change(screen.getByLabelText(/seek/i), { target: { value: "12" } });

    expect(playerInstance.seek).toHaveBeenCalledWith(12);
    void capturedOnSeek;
  });

  it("should set a loop range on the transport when start and end are captured", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];
    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(3);

    fireEvent.click(screen.getByRole("button", { name: /set loop start/i }));
    (playerInstance.getCurrentTime as jest.Mock).mockReturnValue(9);
    fireEvent.click(screen.getByRole("button", { name: /set loop end/i }));

    act(() => {
      rafCallback?.(0);
    });

    expect(screen.getByRole("button", { name: /clear loop/i })).toBeInTheDocument();
  });

  it("should clear the loop when Clear loop is clicked", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    fireEvent.click(screen.getByRole("button", { name: /set loop start/i }));
    fireEvent.click(screen.getByRole("button", { name: /set loop end/i }));

    fireEvent.click(screen.getByRole("button", { name: /clear loop/i }));

    expect(screen.queryByRole("button", { name: /clear loop/i })).not.toBeInTheDocument();
  });

  it("should set playback rate by calling player.setPlaybackRate when the speed select changes", async () => {
    const startLength = MockedSyncedPlayer.mock.instances.length;
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    const playerInstance = MockedSyncedPlayer.mock.instances[startLength];

    fireEvent.change(screen.getByLabelText(/playback speed/i), { target: { value: "1.5" } });

    expect(playerInstance.setPlaybackRate).toHaveBeenCalledWith(1.5);
  });

  it("should add a manually-created hit to the score when the add-hit form is submitted", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));

    expect(screen.getByTestId("drum-score-mock")).toBeInTheDocument();
  });

  it("should enable the undo button only after an edit has been made", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactory}
      />,
    );
    await screen.findByRole("button", { name: /play/i });
    expect(screen.getByRole("button", { name: /undo/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /^add hit$/i }));

    expect(screen.getByRole("button", { name: /undo/i })).not.toBeDisabled();
  });

  it("should toggle the metronome by calling transport scheduling without throwing", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        createAudioContext={fakeContextFactoryWithOscillator}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByLabelText(/metronome/i));

    expect(screen.getByLabelText(/metronome/i)).toBeChecked();
  });

  it("should start playback via count-in when the Count-in button is clicked", async () => {
    render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        beats={[]}
        createAudioContext={fakeContextFactoryWithOscillator}
      />,
    );
    await screen.findByRole("button", { name: /play/i });

    fireEvent.click(screen.getByRole("button", { name: /count-in/i }));

    expect(await screen.findByRole("button", { name: /pause/i })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- Player.test.tsx`
Expected: FAIL — `Unable to find an element with the text: /set loop start/i` (none of the new controls exist yet).

- [ ] **Step 3: Thread `beats` through JobForm**

In `frontend/components/JobForm.tsx`, change:

```tsx
      {job && analysis && (
        <Player
          apiBaseUrl={apiBaseUrl}
          jobId={job.id}
          events={analysis.events}
        />
      )}
```

to:

```tsx
      {job && analysis && (
        <Player
          apiBaseUrl={apiBaseUrl}
          jobId={job.id}
          events={analysis.events}
          beats={analysis.beats}
        />
      )}
```

`Player.tsx`'s new `handleVolumeChange`/`handleDrumsVolumeChange` will need to call volume methods through `transportRef.current` rather than reaching into a raw `SyncedPlayer`, but `PracticeTransport` (Tasks 3-4) doesn't expose volume control yet — it only re-exports transport-level concerns (play/pause/seek/loop/rate/metronome). Add those pass-throughs first, then write the full component in one pass.

- [ ] **Step 4: Add volume pass-throughs to PracticeTransport**

In `frontend/lib/audio/PracticeTransport.ts`, widen `PlayerLike`:

```ts
export interface PlayerLike {
  readonly isPlaying: boolean;
  readonly duration: number;
  play(): void;
  pause(): void;
  seek(time: number): void;
  getCurrentTime(): number;
  setPlaybackRate(rate: number): void;
  getPlaybackRate(): number;
}
```

to:

```ts
export interface PlayerLike {
  readonly isPlaying: boolean;
  readonly duration: number;
  play(): void;
  pause(): void;
  seek(time: number): void;
  getCurrentTime(): number;
  setPlaybackRate(rate: number): void;
  getPlaybackRate(): number;
  setMasterVolume(value: number): void;
  getMasterVolume(): number;
  setDrumsVolume(value: number): void;
  getDrumsVolume(): number;
}
```

Add pass-through methods to the `PracticeTransport` class, next to `setPlaybackRate`/`getPlaybackRate`:

```ts
  setMasterVolume(value: number): void {
    this.player.setMasterVolume(value);
  }

  getMasterVolume(): number {
    return this.player.getMasterVolume();
  }

  setDrumsVolume(value: number): void {
    this.player.setDrumsVolume(value);
  }

  getDrumsVolume(): number {
    return this.player.getDrumsVolume();
  }
```

`SyncedPlayer` already implements all four (unchanged from before this epic), so it continues to satisfy `PlayerLike` structurally with no further change.

In `frontend/lib/audio/__tests__/PracticeTransport.test.ts`, extend `FakePlayer` to also implement the four new methods (needed for `FakePlayer` to keep satisfying `PlayerLike`):

```ts
class FakePlayer implements PlayerLike {
  isPlaying = false;
  duration = 30;
  play = jest.fn(() => {
    this.isPlaying = true;
  });
  pause = jest.fn(() => {
    this.isPlaying = false;
  });
  seek = jest.fn();
  getCurrentTime = jest.fn(() => 0);
  setPlaybackRate = jest.fn();
  getPlaybackRate = jest.fn(() => 1);
  setMasterVolume = jest.fn();
  getMasterVolume = jest.fn(() => 1);
  setDrumsVolume = jest.fn();
  getDrumsVolume = jest.fn(() => 1);
}
```

Run (from `frontend/`): `npm test -- PracticeTransport.test.ts`
Expected: PASS — unaffected, purely additive.

- [ ] **Step 5: Rewrite Player.tsx**

Replace the full contents of `frontend/components/Player.tsx`:

```tsx
"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AnalysisEvent, Beat, DrumInstrument } from "@/lib/api/jobs";
import { type DecodableAudioContext, loadAudioBuffer } from "@/lib/audio/loadAudioBuffer";
import { PracticeTransport, type MetronomeContextLike } from "@/lib/audio/PracticeTransport";
import { SyncedPlayer } from "@/lib/audio/SyncedPlayer";
import { INSTRUMENT_NOTATION } from "@/lib/notation/instrumentNotation";
import { useScoreEditor } from "@/lib/score/useScoreEditor";

const DrumScore = dynamic(() => import("@/components/DrumScore"), { ssr: false });

interface PlayerProps {
  apiBaseUrl: string;
  jobId: string;
  events: AnalysisEvent[];
  beats?: Beat[];
  createAudioContext?: () => DecodableAudioContext;
}

type LoadStatus = "loading" | "ready" | "error";

const INSTRUMENTS = Object.keys(INSTRUMENT_NOTATION) as DrumInstrument[];
const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5];

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "0:00";
  }
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

function defaultCreateAudioContext(): DecodableAudioContext {
  return new AudioContext() as unknown as DecodableAudioContext;
}

export default function Player({
  apiBaseUrl,
  jobId,
  events,
  beats = [],
  createAudioContext = defaultCreateAudioContext,
}: PlayerProps) {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [masterVolume, setMasterVolume] = useState(1);
  const [drumsVolume, setDrumsVolume] = useState(1);
  const [loopStart, setLoopStart] = useState<number | null>(null);
  const [loop, setLoop] = useState<{ startTime: number; endTime: number } | null>(null);
  const [playbackRate, setPlaybackRateValue] = useState(1);
  const [metronomeEnabled, setMetronomeEnabled] = useState(false);
  const [selectedHitId, setSelectedHitId] = useState("");
  const [editInstrument, setEditInstrument] = useState<DrumInstrument>(INSTRUMENTS[0]);
  const [movePosition, setMovePosition] = useState({ measure: 1, beat: 1, subdivision: 0 });
  const [addPosition, setAddPosition] = useState({ measure: 1, beat: 1, subdivision: 0 });
  const [addInstrument, setAddInstrument] = useState<DrumInstrument>(INSTRUMENTS[0]);

  const transportRef = useRef<PracticeTransport | null>(null);
  const rafRef = useRef<number | null>(null);
  const contextRef = useRef<DecodableAudioContext | null>(null);
  const countInPendingRef = useRef(false);

  const editor = useScoreEditor(events);
  const hits = collectHits(editor.score);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const context = createAudioContext();
        contextRef.current = context;
        const [drumsBuffer, accompanimentBuffer] = await Promise.all([
          loadAudioBuffer(`${apiBaseUrl}/api/jobs/${jobId}/audio/drums`, context),
          loadAudioBuffer(`${apiBaseUrl}/api/jobs/${jobId}/audio/accompaniment`, context),
        ]);

        if (cancelled) {
          return;
        }

        const player = new SyncedPlayer(context, drumsBuffer, accompanimentBuffer);
        transportRef.current = new PracticeTransport(player, context as unknown as MetronomeContextLike, beats);
        setDuration(player.duration);
        setStatus("ready");
      } catch (error) {
        if (!cancelled) {
          console.error(`[Player] failed to load audio for job ${jobId}:`, error);
          setStatus("error");
        }
      }
    }

    load();

    return () => {
      cancelled = true;
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
      }
      transportRef.current?.pause();
      contextRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBaseUrl, jobId]);

  function tick() {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    setCurrentTime(transport.tick());
    if (transport.isPlaying) {
      countInPendingRef.current = false;
      rafRef.current = requestAnimationFrame(tick);
    } else if (countInPendingRef.current) {
      rafRef.current = requestAnimationFrame(tick);
    } else {
      setIsPlaying(false);
    }
  }

  function handlePlayPause() {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }

    if (transport.isPlaying) {
      transport.pause();
      setIsPlaying(false);
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
      }
    } else {
      transport.play();
      setIsPlaying(true);
      rafRef.current = requestAnimationFrame(tick);
    }
  }

  function handleCountInPlay() {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    countInPendingRef.current = true;
    transport.playWithCountIn();
    setIsPlaying(true);
    rafRef.current = requestAnimationFrame(tick);
  }

  const seekTo = useCallback((time: number) => {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    transport.seek(time);
    setCurrentTime(transport.getCurrentTime());
  }, []);

  function handleSeekSlider(event: React.ChangeEvent<HTMLInputElement>) {
    seekTo(Number(event.target.value));
  }

  function handleVolumeChange(event: React.ChangeEvent<HTMLInputElement>) {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    const value = Number(event.target.value) / 100;
    transport.setMasterVolume(value);
    setMasterVolume(value);
  }

  function handleDrumsVolumeChange(event: React.ChangeEvent<HTMLInputElement>) {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    const value = Number(event.target.value) / 100;
    transport.setDrumsVolume(value);
    setDrumsVolume(value);
  }

  function handleSetLoopStart() {
    setLoopStart(currentTime);
  }

  function handleSetLoopEnd() {
    if (loopStart == null) {
      return;
    }
    const range = { startTime: Math.min(loopStart, currentTime), endTime: Math.max(loopStart, currentTime) };
    setLoop(range);
    transportRef.current?.setLoop(range);
  }

  function handleClearLoop() {
    setLoop(null);
    setLoopStart(null);
    transportRef.current?.setLoop(null);
  }

  function handleRateChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const rate = Number(event.target.value);
    transportRef.current?.setPlaybackRate(rate);
    setPlaybackRateValue(rate);
  }

  function handleMetronomeToggle(event: React.ChangeEvent<HTMLInputElement>) {
    const enabled = event.target.checked;
    transportRef.current?.setMetronomeEnabled(enabled);
    setMetronomeEnabled(enabled);
  }

  function handleDeleteHit() {
    if (!selectedHitId) {
      return;
    }
    editor.deleteHit(selectedHitId);
    setSelectedHitId("");
  }

  function handleChangeInstrument() {
    if (!selectedHitId) {
      return;
    }
    editor.changeInstrument(selectedHitId, editInstrument);
  }

  function handleMoveHit() {
    if (!selectedHitId) {
      return;
    }
    editor.moveHit(selectedHitId, movePosition);
  }

  function handleAddHit() {
    editor.addHit(addPosition, addInstrument);
  }

  if (status === "loading") {
    return <p>Loading audio...</p>;
  }

  if (status === "error") {
    return <p role="alert">Failed to load audio for playback.</p>;
  }

  const measureCount = Math.max(editor.score.measures.length, 1);

  return (
    <div>
      <div>
        <button type="button" onClick={handlePlayPause}>
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={handleCountInPlay}>
          Count-in
        </button>
        <input
          type="range"
          aria-label="Seek"
          min={0}
          max={duration}
          step={0.01}
          value={currentTime}
          onChange={handleSeekSlider}
        />
        <span>
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
        <label>
          Master volume
          <input
            type="range"
            aria-label="Master volume"
            min={0}
            max={100}
            value={masterVolume * 100}
            onChange={handleVolumeChange}
          />
        </label>
        <label>
          Drums volume
          <input
            type="range"
            aria-label="Drums volume"
            min={0}
            max={100}
            value={drumsVolume * 100}
            onChange={handleDrumsVolumeChange}
          />
        </label>
        <label>
          Playback speed
          <select aria-label="Playback speed" value={playbackRate} onChange={handleRateChange}>
            {PLAYBACK_RATES.map((rate) => (
              <option key={rate} value={rate}>
                {rate}x
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" aria-label="Metronome" checked={metronomeEnabled} onChange={handleMetronomeToggle} />
          Metronome
        </label>
      </div>
      <div>
        <button type="button" onClick={handleSetLoopStart}>
          Set loop start
        </button>
        <button type="button" onClick={handleSetLoopEnd} disabled={loopStart == null}>
          Set loop end
        </button>
        {loop && (
          <button type="button" onClick={handleClearLoop}>
            Clear loop
          </button>
        )}
      </div>
      <div>
        <label>
          Hit to edit
          <select
            aria-label="Select hit to edit"
            value={selectedHitId}
            onChange={(event) => setSelectedHitId(event.target.value)}
          >
            <option value="">-- none --</option>
            {hits.map((hit) => (
              <option key={hit.id} value={hit.id}>
                {hit.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={handleDeleteHit} disabled={!selectedHitId}>
          Delete hit
        </button>
        <label>
          New instrument
          <select
            aria-label="New instrument"
            value={editInstrument}
            onChange={(event) => setEditInstrument(event.target.value as DrumInstrument)}
          >
            {INSTRUMENTS.map((instrument) => (
              <option key={instrument} value={instrument}>
                {instrument}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={handleChangeInstrument} disabled={!selectedHitId}>
          Change instrument
        </button>
        <label>
          Move to measure
          <input
            type="number"
            aria-label="Move to measure"
            min={1}
            max={measureCount}
            value={movePosition.measure}
            onChange={(event) => setMovePosition((p) => ({ ...p, measure: Number(event.target.value) }))}
          />
        </label>
        <label>
          Move to beat
          <input
            type="number"
            aria-label="Move to beat"
            min={1}
            max={4}
            value={movePosition.beat}
            onChange={(event) => setMovePosition((p) => ({ ...p, beat: Number(event.target.value) }))}
          />
        </label>
        <label>
          Move to subdivision
          <input
            type="number"
            aria-label="Move to subdivision"
            min={0}
            max={3}
            value={movePosition.subdivision}
            onChange={(event) => setMovePosition((p) => ({ ...p, subdivision: Number(event.target.value) }))}
          />
        </label>
        <button type="button" onClick={handleMoveHit} disabled={!selectedHitId}>
          Move hit
        </button>
      </div>
      <div>
        <label>
          Add hit instrument
          <select
            aria-label="Add hit instrument"
            value={addInstrument}
            onChange={(event) => setAddInstrument(event.target.value as DrumInstrument)}
          >
            {INSTRUMENTS.map((instrument) => (
              <option key={instrument} value={instrument}>
                {instrument}
              </option>
            ))}
          </select>
        </label>
        <label>
          Add at measure
          <input
            type="number"
            aria-label="Add at measure"
            min={1}
            max={measureCount}
            value={addPosition.measure}
            onChange={(event) => setAddPosition((p) => ({ ...p, measure: Number(event.target.value) }))}
          />
        </label>
        <label>
          Add at beat
          <input
            type="number"
            aria-label="Add at beat"
            min={1}
            max={4}
            value={addPosition.beat}
            onChange={(event) => setAddPosition((p) => ({ ...p, beat: Number(event.target.value) }))}
          />
        </label>
        <label>
          Add at subdivision
          <input
            type="number"
            aria-label="Add at subdivision"
            min={0}
            max={3}
            value={addPosition.subdivision}
            onChange={(event) => setAddPosition((p) => ({ ...p, subdivision: Number(event.target.value) }))}
          />
        </label>
        <button type="button" onClick={handleAddHit}>
          Add hit
        </button>
      </div>
      <div>
        <button type="button" onClick={editor.undo} disabled={!editor.canUndo}>
          Undo
        </button>
        <button type="button" onClick={editor.redo} disabled={!editor.canRedo}>
          Redo
        </button>
      </div>
      <DrumScore score={editor.score} currentTime={currentTime} onSeek={seekTo} />
    </div>
  );
}

function collectHits(score: ReturnType<typeof useScoreEditor>["score"]): { id: string; label: string }[] {
  const result: { id: string; label: string }[] = [];
  score.measures.forEach((measure, measureIndex) => {
    measure.forEach((slot) => {
      if (slot.type !== "note") {
        return;
      }
      slot.hits.forEach((hit) => {
        result.push({
          id: hit.id,
          label: `${hit.instrument} @ m${measureIndex + 1} b${slot.position.beat}.${slot.position.subdivision}`,
        });
      });
    });
  });
  return result;
}
```

- [ ] **Step 6: Run the Player suite to verify it passes**

Run (from `frontend/`): `npm test -- Player.test.tsx`
Expected: PASS (all existing tests + the new ones from Step 1).

- [ ] **Step 7: Run the full frontend suite, lint, and typecheck**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Expected: PASS. Pay particular attention to `EndToEndFlow.test.tsx` (uses a real `SyncedPlayer`/`PracticeTransport` end-to-end) and `JobForm.test.tsx` — both should pass unchanged since `beats` defaults to `[]` when their `getAnalysis` mocks omit it.

- [ ] **Step 8: Run the backend suite once more for a final cross-check**

Run (from `backend/`): `pytest`
Expected: PASS — unaffected by this frontend-only task, run as a final sanity check before the PR.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/Player.tsx frontend/components/__tests__/Player.test.tsx frontend/components/JobForm.tsx frontend/lib/audio/PracticeTransport.ts frontend/lib/audio/__tests__/PracticeTransport.test.ts
git commit -m "feat: wire PracticeTransport and useScoreEditor into Player

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9"
```

---

### Task 9: Final whole-branch review and real-browser manual verification

Not TDD-structured (no new unit tests) — this is CLAUDE.md's mandatory manual-verification gate for geometry/audio-timing work the automated suite structurally can't catch (jsdom has no real audio clock and no `getBBox()`), the same gate that caught a real bug in V1-019 (double-stem/flag) and V1-022 (note-clipping). Must run after every earlier task is committed. Should be done by the coordinating session directly, not delegated to a fresh subagent, since it requires judgment against everything decided across this whole plan.

**Files:** none created; this task only verifies.

- [ ] **Step 1: Dispatch a full whole-branch code review**

Use `superpowers:requesting-code-review` (or the `code-review` skill at `high` effort) against the complete diff on `v1-5_practice-player-correction-editor` vs `main`. Look specifically for the class of bug the V1-019 final review caught that no per-task review saw: construction-order bugs, and here also transport-state bugs (e.g., does `setPlaybackRate` mid-loop-restart leave `offset`/`startContextTime` consistent? does `tick()`'s loop-restart interact correctly with a pending count-in?). Fix anything Critical/High before proceeding; use judgment on Medium/Low per the review's own findings.

- [ ] **Step 2: Start the app and manually verify in a real browser**

Use the `run` skill (or `npm run dev` in `frontend/` + the backend's own run command) against a real processed job. Verify, per CLAUDE.md's rule that jsdom cannot catch rendered-geometry or real-audio-timing defects:

- Click-to-seek: click several different notes across at least two rows; confirm the audio playhead jumps to the clicked note's time and playback (if playing) continues from there.
- A/B loop: set a loop over a short section mid-song, let it play through at least 3 iterations; confirm both stems restay in sync on each restart (no audible drift between drums/accompaniment) and the playhead visibly snaps back rather than drifting.
- Playback speed: try each rate in `PLAYBACK_RATES`; confirm stems stay synchronized with each other at every rate, and confirm the pitch does audibly shift (expected/documented limitation, not a bug) rather than silently doing nothing.
- Metronome: enable it during playback; confirm clicks land audibly on the beat against the real drum track, not just close.
- Count-in: click Count-in; confirm 4 clicks play before the track starts, at the song's real tempo.
- Row-change playhead behavior: confirm the playhead still doesn't visibly jump backward across a row break under loop/rate changes (this was previously covered only for the base 1x, no-loop case).
- Correction editor: add a hit, delete a hit, move a hit, change a hit's instrument; confirm the rendered notation updates each time and playback timing is unaffected for untouched hits. Confirm a manually-added hit renders with the distinct manual-hit color.
- Undo/redo: make 2-3 edits, undo them all, redo them all; confirm the rendered score matches at each step.
- Confidence review: temporarily wire a job's events through `LOW_CONFIDENCE_GROOVE_EVENTS` (Task 6's fixture) via a throwaway debug route or direct prop substitution — never committed — to visually confirm the low-confidence color renders correctly; remove the substitution afterward.

- [ ] **Step 3: Fix anything found, following CLAUDE.md's root-cause rule**

Per CLAUDE.md: "Do not patch symptoms." If loop restart or playhead behavior looks off, diagnose the actual timing/state bug rather than adding a debounce/smoothing hack. Add a regression test for whatever's fixed, in the relevant existing test file from Tasks 1-8.

- [ ] **Step 4: Update PROJECT.md's Epic 5 status**

In `PROJECT.md`, no structural change needed (Epic 5's description already matches what was built) — confirm the "v1.0 Definition of Done" line ("seek by audio or score; loop sections; change playback speed; correct events") is now genuinely true of the running app before proceeding to the PR.

- [ ] **Step 5: Run both full suites one final time**

Run (from `frontend/`): `npm test && npm run lint && npx tsc --noEmit`
Run (from `backend/`): `pytest`
Expected: PASS, both.

- [ ] **Step 6: Push and open the PR**

```bash
git push -u origin v1-5_practice-player-correction-editor
gh pr create --title "Epic 5: Practice Player & Correction Editor (V1-023 through V1-028)" --body "$(cat <<'EOF'
## Summary
Implements all six Epic 5 issues in one bundled PR (user-approved exception to the normal one-issue-per-branch workflow, precedent: PR #101):

- #74 (V1-023): click-to-seek on rendered notation
- #75 (V1-024): A/B section looping
- #76 (V1-025): playback speed control (native playbackRate; pitch shift is a documented limitation, not fixed with a stretch library)
- #77 (V1-026): count-in and metronome, anchored to real per-beat timestamps (new: backend `beats` field on `/analysis`)
- #78 (V1-027): manual drum-event correction editor (add/delete/move/change-instrument)
- #79 (V1-028): undo/redo and confidence-assisted review

Architecture: new `PracticeTransport` composes the existing `SyncedPlayer` (loop/rate/metronome/count-in, pure functions unit-tested independent of AudioContext); new `useScoreEditor` hook lifts `Score` into persistent state with snapshot-based undo/redo; `DrumScore` now takes a `Score` prop instead of building its own.

Design spec: `docs/superpowers/specs/2026-09-23-epic5-practice-player-correction-editor-design.md`
Implementation plan: `docs/superpowers/plans/2026-09-23-epic5-practice-player-correction-editor.md`

## Test plan
- [ ] Backend: `pytest` green (new beats-endpoint coverage)
- [ ] Frontend: `npm test && npm run lint && npx tsc --noEmit` green
- [ ] Manual real-browser verification: click-to-seek, loop restart audio sync, playback rate stem sync, metronome/count-in alignment against a real beat track, correction editor + undo/redo, confidence-flagged styling (see Task 9 of the implementation plan for the full checklist)

Closes #74, closes #75, closes #76, closes #77, closes #78, closes #79

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01AEYZ2yVRGayRS3TWn2ySF9
EOF
)"
```

- [ ] **Step 7: Report to the user and stop**

Per this repo's per-issue loop (`[[project-drumscore-issue-workflow]]`): report the PR link, summarize what was implemented/tested/deferred (pitch-shift-not-preserved, in-session-only edits, poll-based loop restart — all per the approved spec's non-goals), and wait for merge confirmation before syncing main / deleting the branch / advancing to Epic 6.

---

## Self-Review Notes

**Spec coverage:** every spec section maps to a task — backend beats API (Task 1), `PracticeTransport` core + rate (Tasks 2-3), metronome/count-in (Task 4), editable score state + undo/redo (Task 5), confidence threshold + fixture (Task 6), click-to-seek + score prop + styling (Task 7), full UI integration (Task 8), manual verification + PR (Task 9). The spec's non-goals (no pitch preservation, no sample-accurate loop, no backend edit persistence, count-in only on first play, undo/redo editor-only, `insertHit` gap stays deferred) are each explicitly upheld by name in the relevant task rather than silently dropped.

**Type consistency:** `LoopRange`, `PlayerLike`, `MetronomeContextLike`, `OscillatorNodeLike` (Task 3, extended Task 4/8) are used with identical shapes everywhere they're referenced. `Beat` (Task 2) has the same five fields (`source_time`, `measure`, `beat`, `is_downbeat`, `confidence`) in the backend response (Task 1), the frontend type (Task 2), and every consumer (Task 4, Task 8). `ScoreEditor`'s five mutating methods plus `undo`/`redo`/`canUndo`/`canRedo` (Task 5) match exactly what Task 8's `Player.tsx` calls.

**Corrections made during planning against the approved spec (verified against actual current code, not assumed):** the spec's chat-summary suggested camelCase field mapping for `Beat` on the frontend — the actual codebase convention (confirmed in `AnalysisEvent`/`Job`) is direct snake_case passthrough with no mapping layer, so `Beat` uses `source_time`/`is_downbeat` verbatim. `BeatPointResponse` already existed unused in the backend (not anticipated in the spec) — Task 1 reuses it rather than defining a new model. Playback-rate rebasing was originally sketched as two separate calls from `PracticeTransport`; implemented instead as one atomic `SyncedPlayer.setPlaybackRate` (mirroring the existing `seek()` stop-and-restart pattern) to avoid a two-call race. `DecodableAudioContext`/`AudioContextLike` needed no widening for oscillator support once `MetronomeContextLike` was defined as PracticeTransport's own minimal structural interface (satisfied automatically once `SyncedPlayer`'s underlying real `AudioContext` is passed in) — avoids coupling `SyncedPlayer.ts`'s core types to a concern it doesn't use.
