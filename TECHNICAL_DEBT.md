# Technical debt

Things found along the way that are deliberately deferred rather than
fixed on the spot, so they don't get lost. Reviewed and addressed as
part of **MVP-011 — Tests and hardening** (see `PROJECT.md`).

Each entry: what it is, where it came from, and what fixing it would
involve. Entries fixed during MVP-011 are marked **Resolved** with a
short note on what changed; the rest are marked **Deferred** with why.

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

**Partially resolved (MVP-011):** `LibrosaTempoEstimator` now detects
onsets and picks whichever of `tempo`, `tempo*2`, or `tempo/2` best
fits their positions, correcting the common case where a beat tracker
reports exactly half or double the true tempo. This does **not** fix
the specific case originally observed (123 vs. 184.6 BPM): that's a
1.5x ratio (simple-vs-compound meter ambiguity), not a clean octave
error, and isn't addressed by this heuristic. Fixing that specific
case would still need cross-validating against DrumScript's own tempo
estimate, which isn't currently piped through to the mapping step —
left as further work, not done here.

---

## Generated notation doesn't look/read quite right yet

**Found in:** MVP-007 manual verification (user feedback after reviewing
a real generated score)

User's own words: doesn't like how it looks, doesn't feel fully correct
yet — needs to be sharpened for better accuracy. Two distinct issues
bundled under this:

1. **Visual noise from unconsolidated rests.** Empty 16th-note slots
   are each rendered as their own individual rest instead of being
   merged into larger rest values (a full measure of silence renders
   as 16 separate 16th rests instead of one whole rest). This is a
   pure rendering/engraving problem in `buildScore.ts` /
   `DrumScore.tsx` — the underlying event data and timestamps are
   unaffected.
2. **Classification accuracy.** DrumScript's rule-based classifier
   (see MVP-005) produces a plausible but imperfect transcription —
   expected per its own docs to be weakest outside fast/metal genres.
   This is a fundamental limitation of the chosen approach, not a
   quick fix (see the MVP-005 evaluation notes in git history for why
   alternatives were rejected).

**Fix would involve:**
- Rest consolidation: post-process each measure's rest run into the
  fewest correctly-tied rest values (whole/half/quarter/etc.) before
  building `StaveNote`s — a contained, testable change to
  `buildScore.ts`.
- Accuracy: no quick fix. Options to revisit later: tune DrumScript's
  physics thresholds against a labeled sample of real songs, swap in
  or blend a different transcription engine behind the existing
  `DrumTranscriber` interface, or expose a manual-correction UI
  (already on the MVP roadmap as a post-MVP feature).

**Partially resolved (MVP-011):** Rest consolidation is done —
`buildScore.ts`'s `consolidateRests` merges each run of consecutive
16th-note rests into the fewest correctly-aligned rest values (e.g. a
full empty measure now renders as one whole rest instead of 16).
Classification accuracy is unchanged: reviewed and deliberately left
as-is, since it's a fundamental limitation of DrumScript's rule-based
approach rather than something fixable within this task, per the
options above.

---

## No auto-scroll to follow the playhead during playback

**Found in:** MVP-008 design discussion

The user wants the notation view to auto-scroll and keep the moving
playhead visible during playback, but it isn't in PROJECT.md's roadmap
anywhere yet. Deferred out of MVP-008 to keep that task scoped to the
playback engine itself; not forgotten.

**Fix would involve:** in the Player/DrumScore integration, watching
the playhead's current row and calling `scrollIntoView` (or manual
scroll math) on the row's stave element when it's about to leave the
viewport, without fighting the user's own manual scrolling.

**Partially resolved (MVP-011):** `timeline.ts`'s
`computeAutoScrollLeft` keeps the playhead horizontally in view within
the score's own scrollable container (only nudging `scrollLeft` when
the playhead is about to leave the visible area), verified in a real
browser at a narrow viewport. Vertical auto-scroll to a new row isn't
included: the container currently has no capped height (all rows are
already visible without scrolling), so there's nothing to scroll
vertically yet — revisit if the container ever gets a fixed height.

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

## Quantization grid isn't phase-aligned to the beat

**Found in:** Manual testing, 2026-09-20 (generated notation doesn't hold
4/4 structure, doesn't read as a coherent groove). Full analysis in
`docs/status/2026-09-20-current-app-state.md`, section 4.

`beat_mapping.py`'s `quantize_events()` assumes measure 1 / beat 1 starts
exactly at `event.time = 0` (the very start of the audio) and snaps every
event to the nearest 16th-note position on a constant-tempo grid anchored
there. Real recordings almost never have their first downbeat exactly at
t=0 — there's usually silence or a pickup before it. If the grid's phase
is off, even a perfectly, metronomically played drum part gets quantized
incorrectly, because the grid itself isn't aligned with the music. Not
confirmed as THE cause of the messy notation in the reported screenshot,
but a strong candidate — not previously logged anywhere.

**Fix would involve:** detecting the actual first strong onset (or reusing
an onset-detection pass already available via `librosa.onset.onset_detect`
in `librosa_tempo_estimator.py`) and using it as the grid's phase offset
instead of assuming t=0, before quantizing in `quantize_events()`.

---

## Notation never consolidates note durations — every hit renders as a 16th note

**Found in:** Manual testing, 2026-09-20 (notation looks denser/busier
than reference examples). Full analysis in
`docs/status/2026-09-20-current-app-state.md`, section 3.

`buildScore.ts`'s `consolidateRests` merges runs of empty 16th-note slots
into larger rest values (resolved in MVP-011, see above), but there's no
equivalent for notes: `buildNoteSpec` always hard-codes
`duration: "16"` for a hit, regardless of whether the underlying rhythm
would idiomatically read as quarter or eighth notes. Combined with the
phase/grid issue above, this makes the rendered score look busier than
the reference examples the user provided, which use coarser note values
where the actual rhythm is sparser.

**Fix would involve:** a note-duration consolidation pass symmetric to
`consolidateRests`, merging consecutive same-instrument (or same-slot-set)
hits into the largest note value the beat grid allows, before building
`StaveNote`s.

---

## Open hi-hat notated via articulation, not a ring notehead

**Found in:** Manual testing, 2026-09-20 — user-provided reference
notation (see `docs/status/2026-09-20-current-app-state.md`, section 3)
marks open hi-hat with a circle/ring around the notehead, a common drum-
notation convention. `instrumentNotation.ts` instead uses the same
notehead as closed hi-hat (`g/5/x2`) plus a VexFlow articulation
(`"ah"`) drawn above the note. Both are visually distinguishable per
PROJECT.md §6's literal requirement, but don't match the reference style,
and the articulation glyph may be contributing to the "very cluttered"
look reported if it's rendering above notes more often than expected.

**Fix would involve:** checking whether VexFlow supports a circled-notehead
modifier (rather than an articulation) for open hi-hat, and switching to
it if so, for a closer match to standard drum-notation convention.

---

## Playhead position uses a constant-tempo approximation instead of the real audio clock

**Found in:** Manual testing, 2026-09-20 (playhead jumps back and forth
unevenly during playback rather than advancing steadily). Full analysis
in `docs/status/2026-09-20-current-app-state.md`, section 6.

`SyncedPlayer.getCurrentTime()` itself is correctly built per PROJECT.md's
"audio clock is the source of truth" rule — it always derives from
`AudioContext.currentTime`. But `DrumScore.tsx` places the playhead by
building a `TimelinePoint[]` list where each point's `time` comes from
`computeSlotTimeSeconds(measure, beat, subdivision, tempoBpm, ...)` — a
constant-tempo formula, decoupled from the real per-event audio
timestamps. Every animation frame, the real audio time is looked up
against this constant-tempo-approximated list via `interpolatePlayheadX`.
If the song's real tempo isn't perfectly constant, or the quantization
grid is phase-shifted (see above), the real time and the approximated
grid time drift apart as the song plays, which could produce exactly this
symptom — especially visible across row breaks, where a small timing
error produces a large visual jump in x/y.

**Not confirmed** — this is a code-reading hypothesis, not verified with
a live repro/instrumentation yet. An alternate, not-yet-ruled-out
possibility: if the `events` prop passed into `DrumScore` doesn't have a
stable reference across re-renders, the whole score (and its
`timelineRef`) could be getting rebuilt on every tick during playback,
which would also look like the playhead jumping.

**Fix would involve:** first, a live repro with instrumentation
(systematic-debugging) to confirm which of the two hypotheses above is
the actual cause, before changing anything. If it's the constant-tempo
mismatch, the fix likely means deriving playhead position from the
original `event.time` values (already preserved on each `DrumEvent`)
instead of re-deriving time from the quantized measure/beat/subdivision
and a single BPM.

---

## Unconfirmed `AbortError: The operation was aborted.` during manual testing

**Found in:** Manual testing, 2026-09-20, shown in the Next.js dev error
overlay while loading a job's audio. Full analysis in
`docs/status/2026-09-20-current-app-state.md`, section 7.

A grep across the entire frontend codebase shows zero uses of
`AbortController`/`AbortSignal` — the app never aborts a fetch itself.
The error most likely originates from the dev environment (e.g. Turbopack
Fast Refresh/HMR cancelling an in-flight request while one of the two
~45MB audio fetches is still loading) rather than from application code,
but this is **not confirmed**.

**Fix would involve:** first reproducing with the full browser console
stack trace and exact repro steps (what was happening right before the
error) to determine whether this is a real production-path bug or a
dev-only artifact, before deciding on a fix.
