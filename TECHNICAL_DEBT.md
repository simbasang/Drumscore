# Technical debt

Things found along the way that are deliberately deferred rather than
fixed on the spot, so they don't get lost. Reviewed and addressed as
part of **MVP-011 — Tests and hardening** (see `PROJECT.md`), unless
picked up sooner.

Each entry: what it is, where it came from, and what fixing it would
involve.

---

## Disk cleanup for job files

**Found in:** MVP-004.5 review

Nothing removes old jobs' downloaded audio, separated stems, or
transcription output under `backend/data/jobs/`. Disk usage grows
unbounded as jobs accumulate.

**Fix would involve:** a retention policy (age-based or count-based)
and a cleanup task (scheduled or triggered on new job creation).

---

## No concurrency limit on heavy pipeline jobs

**Found in:** MVP-004.5 review

Each job spawns its own Demucs subprocess (and, from MVP-005 on, its
own DrumScript subprocess) with no cap on how many can run at once.
Several simultaneous submissions could exhaust CPU/RAM.

**Fix would involve:** a job queue or semaphore limiting how many
pipeline runs execute concurrently, with the rest waiting in `queued`.

---

## No retry for failed pipeline steps

**Found in:** MVP-004.5 review (not previously in PROJECT.md's plan)

A job that fails has no way to be re-run — the user has to submit the
same URL again as a brand-new job.

**Fix would involve:** a `POST /api/jobs/{id}/retry`-style endpoint (or
similar) that re-runs the pipeline from the failed step using the
job's existing state, rather than starting over from scratch.

---

## Tempo estimation disagrees with DrumScript's own estimate

**Found in:** MVP-006 manual verification

Our independent `LibrosaTempoEstimator` (used for beat/measure
mapping) produced ~123 BPM on a test track, while DrumScript's own
internal tempo estimate (visible in its transcription logs, not
currently consumed by us) was ~184.6 BPM on similar material. `123 ×
1.5 ≈ 184.6` — a classic pulse-level ambiguity (simple vs. compound
meter interpretation of the same rhythm), not a bug in either
estimator, but it means the two tempo values used across the pipeline
can disagree.

**Fix would involve:** picking one tempo source consistently (or
cross-validating both and preferring the one with higher confidence),
and/or adding octave-error correction (e.g. checking whether
half/double the detected tempo fits the onset grid better) to
`LibrosaTempoEstimator`.

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
