# Technical debt — resolved

Archive of `TECHNICAL_DEBT.md` entries that are fully resolved or
superseded. Kept for history; not required reading.

---

## Disk cleanup for job files

**Found in:** MVP-004.5 review

Nothing removes old jobs' downloaded audio, separated stems, or
transcription output under `backend/data/jobs/`. Disk usage grows
unbounded as jobs accumulate.

**Fix would involve:** a retention policy (age-based or count-based)
and a cleanup task (scheduled or triggered on new job creation).

**Resolved (MVP-011):** `app/job_cleanup.py` removes any job (store
entry and its `data/jobs/<id>` directory) older than 24 hours,
triggered at the top of `POST /api/jobs`.

**Superseded (Epic 6 Slice A):** replaced by the pruner's retention
rules, see docs/PERSISTENCE.md.

---

## No concurrency limit on heavy pipeline jobs

**Found in:** MVP-004.5 review

Each job spawns its own Demucs subprocess (and, from MVP-005 on, its
own DrumScript subprocess) with no cap on how many can run at once.
Several simultaneous submissions could exhaust CPU/RAM.

**Fix would involve:** a job queue or semaphore limiting how many
pipeline runs execute concurrently, with the rest waiting in `queued`.

**Resolved (MVP-011):** `app/job_processor.py`'s
`PipelineConcurrencyLimiter` wraps `run_pipeline` in a bounded
semaphore (default: 2 concurrent), used by both job creation and
retry. A job waiting for a slot stays in whatever status it already
has.

**Superseded (Epic 6 Slice A):** worker process count
(`WORKER_CONCURRENCY`) bounds concurrent pipelines.

---

## No retry for failed pipeline steps

**Found in:** MVP-004.5 review (not previously in PROJECT.md's plan)

A job that fails has no way to be re-run — the user has to submit the
same URL again as a brand-new job.

**Fix would involve:** a `POST /api/jobs/{id}/retry`-style endpoint (or
similar) that re-runs the pipeline from the failed step using the
job's existing state, rather than starting over from scratch.

**Resolved (MVP-011):** `run_pipeline` now checks the job's existing
`audio_path`/`drums_path`/`events` and skips any step whose output is
already present. `POST /api/jobs/{id}/retry` (404 if unknown, 409 if
not `failed`) clears the job's error, resets it to `queued`, and
re-submits it through the same pipeline.

---

## AudioContext is never closed, leaking across job resubmissions

**Found in:** Post-MVP-008 full app review

Every time `Player` mounts (i.e. every time a job's score becomes
playable), `createAudioContext()` constructs a `new AudioContext()`,
but neither `Player`'s unmount cleanup nor `SyncedPlayer` ever calls
`.close()` on it — confirmed by inspection, there is no `.close()`
call anywhere in `lib/audio/` or `components/Player.tsx`. Submitting
several jobs in the same browser tab without a full page reload
accumulates open `AudioContext` instances. Browsers cap the number of
concurrent contexts per page (Chrome enforces a hard limit, typically
in the single digits); once hit, creating a new context fails and
playback breaks entirely until the page is reloaded.

**Fix would involve:** calling `context.close()` in `Player`'s effect
cleanup, alongside the existing `playerRef.current?.pause()` call,
guarding against double-closing a context that's already closing.

**Resolved (MVP-011):** `Player` now tracks its `AudioContext` in a
ref and calls `context.close()` in the effect cleanup, right after
`playerRef.current?.pause()`.

---

## Playback doesn't stop or reset when a song reaches its end

**Found in:** Post-MVP-008 full app review (reproduced in a real browser)

`SyncedPlayer` has no `onended` handling on its `AudioBufferSourceNode`s,
and its `isPlaying` flag is only ever cleared by an explicit `pause()`
call. Reproduced concretely: seeked to near the end of a real generated
67-second track, pressed Play, and waited past the track's end — the UI
got stuck showing "Pause" with a **current time exceeding the total
duration** (displayed "1:27 / 1:07"), no audio playing, no error in the
console. `getCurrentTime()` keeps growing indefinitely after the track
ends because it's still deriving from the running `AudioContext` clock
with no upper bound check. Compounding this, `play()` doesn't clamp
`offset` the way `seek()` does, so pausing and pressing play again from
this overshot state would pass an out-of-range offset (greater than the
buffer's duration) to `AudioBufferSourceNode.start()`.

**Fix would involve:** listening for `onended` on the buffer sources
(or comparing `getCurrentTime()` against `duration` on each tick) to
auto-pause and clamp the offset back when playback naturally finishes,
and clamping `offset` in `play()` the same way `seek()` already does.

**Resolved (MVP-011):** `SyncedPlayer.getCurrentTime()` now detects
when elapsed time reaches `duration`, stops the sources, clamps the
offset, and flips `isPlaying` to false; `play()` clamps a stale offset
the same way `seek()` does. `Player`'s raf tick reflects the player's
own stopped state back into the UI (button flips back to "Play").
Verified in a real browser: seeking to near the end and letting it
play through stops cleanly at the exact duration.

---

## A single transient polling error silently and permanently stops job status updates

**Found in:** Post-MVP-008 full app review

`JobForm`'s polling loop wraps each `getJob` call in a `try/catch` that
calls `stopPolling()` on any exception at all, including one caused by
a single transient network blip. There's no retry and no user-visible
error — the status text just freezes wherever it last was, which looks
identical to a slow-but-working pipeline.

**Fix would involve:** only stopping polling after N consecutive
failures (or on a definitive 404 for the job), and showing a "lost
connection, retrying..." message rather than failing silently on the
first hiccup.

**Resolved (MVP-011):** `JobForm` now tolerates up to 2 consecutive
polling failures before giving up, showing a "Lost connection,
retrying..." message in between; a subsequent success clears it and
resumes normal status updates.

---

## Playback playhead used a constant-tempo approximation instead of the real audio clock — resolved in V1-010

**Found in:** Post-MVP-008 full app review (`docs/status/2026-09-20-current-app-state.md`, section 6)

`DrumScore`'s playhead position was computed by
`computeSlotTimeSeconds(measure, beat, subdivision, tempoBpm, ...)` — a
pure constant-tempo formula that placed each rendered note slot on a
grid derived from a single scalar BPM, completely decoupled from the
real per-event audio timestamps produced by transcription. Any
deviation between the true tempo (which can drift, or which the
single detected BPM only approximates) and the constant grid would
compound sample-by-sample over the length of a song, so the visual
playhead could drift further and further from the actual audio by the
end of a track even though each individual note was transcribed at
the correct source time — the rendering path simply never consulted
that source time.

**Fix would involve:** threading each event's real source timestamp
through score-building and layout so the playhead is positioned from
actual audio time rather than a recomputed constant-tempo grid, with
interpolation only across slots (rests) that have no real timestamp of
their own.

**Resolved (V1-010):** `DrumScore` now builds its playhead timeline from
each rendered note slot's real `AnalysisEvent.time` values (threaded
through `buildMeasures`'s `NoteSpec.sourceTimes`), interpolating only
across rest slots between two real anchors - not from
`computeSlotTimeSeconds`/a single BPM, which has been deleted as dead code
now that `DrumScore` was its only caller. The backend's `run_tempo_mapping`
also now quantizes events with `quantize_events_with_beats` (real detected
beat anchors, phase-aligned, not a t=0 grid) whenever at least two beats
are detected; as of V1-011, a job whose beat detection cannot produce at
least two beat anchors fails outright instead of falling back to a
constant grid - the fallback and its `quantize_events`/
`musical_position_to_seconds` grid functions have been deleted - see
`docs/superpowers/plans/2026-09-21-source-linked-playhead-timeline.md` and
`docs/superpowers/plans/2026-09-21-remove-legacy-scalar-bpm-path.md`.
