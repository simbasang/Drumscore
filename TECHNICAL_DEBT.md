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

---

## Diagnostics `quantization_error_seconds` is wrong for events that trigger the measure-shift

**Found in:** V1-011 final review

`run_tempo_mapping` (`backend/app/job_processor.py`) shifts every stored
event's `measure` by a uniform `shift` whenever `quantize_events_with_beats`
placed any event before the first detected beat (extrapolated `measure <= 0`),
so the frontend's 1-based `buildMeasures` doesn't silently drop it. It stores
the *unshifted* `beats` list alongside the *shifted* events. `/diagnostics`
(`build_event_diagnostics` in `backend/app/diagnostics.py`) then reconstructs
`quantized_time` from the shifted `measure`/`beat`/`subdivision` against the
unshifted `beats` anchors via `beat_anchored_position_to_seconds`, so the two
disagree by `shift * beats_per_measure * period` seconds whenever a shift
happened.

Worked example (`FakeOffsetBeatDetector` fixture, first beat at 2.5s =
measure 1 beat 1), for an event at t=0.5s: `quantize_events_with_beats`
places it at measure 0/beat 1/subdivision 0; the measure-shift stores it as
measure 1; `beat_anchored_position_to_seconds(beats, 1, 1, 0)` reconstructs
2.5s, so the endpoint reports `quantization_error_seconds` of +2.0s for a
hit that was actually exactly on the grid.

This predates V1-011 (both halves landed in V1-010), but V1-011 made the
beat-anchored reconstruction path unconditional, so it's now the only
reconstruction path - worth recording now that there's no remaining
alternative path to mask it. Impact is confined to the `/diagnostics`
inspection endpoint; playback, score rendering, and stored `event.time` are
unaffected.

**Fix would involve:** shifting the stored `beats` list by the same amount
as the events (so quantization and its inverse share one origin), or
reporting `quantized_time`/`quantization_error_seconds` from the pre-shift
measure values. `test_run_tempo_mapping_quantizes_with_beats_and_stores_them`
(`backend/tests/test_job_processor.py`) already uses the offset-beats
fixture, so a regression test is cheap to add alongside the fix.

**Deferred:** out of scope for V1-011 (#44) - tracked here for a follow-up
GitHub issue against Epic 2/3 diagnostics tooling.

---

## Benchmark corpus's synthetic audio doesn't exercise DrumScript's classifier realistically

**Found in:** V1-016 (#49) post-processing investigation

The Epic 3 benchmark corpus (`backend/tests/fixtures/benchmark_corpus.py`)
synthesizes each instrument as either an enveloped sine tone (kick, toms
- same exponential decay envelope as the noise-based instruments, only
the carrier waveform differs) or white noise with an exponential decay
envelope (snare, hi-hats, crash, ride) - deliberately simple and
copyright-free, following the existing
`diagnostic_songs.py` pattern. Running the real `DrumScriptTranscriber`
against this corpus (`backend/tests/test_transcription_benchmark.py`)
measured a corpus-wide F1 of only 0.0671, with near-total non-detection
of the sine-tone instruments (kick, toms) and systematic misclassification
among the noise-based instruments (e.g. `ride_groove`'s real ride pattern
is overwhelmingly predicted as crash or hi-hat-open instead of ride) - see
`docs/transcription-post-processing-investigation.md` for the full
per-song breakdown.

This number should not be read as "DrumScript is a poor transcriber" -
DrumScript's rule-based physics classifier (peak frequency, spectral
centroid, energy ratios, decay) was tuned against real drum recordings,
whose transients have broadband, non-stationary spectral content that a
clean sine tone or flat-spectrum noise burst doesn't reproduce. The
benchmark corpus is honest about measuring *this specific synthetic
corpus's* accuracy, which is what issues #45/#46 asked for, but it is not
a proxy for DrumScript's real-world accuracy on actual recordings.

**Fix would involve:** run DrumScript against **IDMT-SMT-Drums**, a
published, ground-truth-labelled dataset of real drum recordings that
`drumscript`'s own package already ships a loader for
(`drumscript/datasets/idmt.py` in the installed package - handles both
the dataset's XML and Sonic Visualiser SVL annotation formats, and maps
its `RealDrum`/`WaveDrum`/`TechnoDrum` subsets' onsets to `kick`/`snare`/
`hi_hat_closed`+`hi_hat_open`). This gives a real accuracy number against
real transients instead of a synthetic proxy - PROJECT.md's own Quality
gates rule ("audio/ML work requires representative real-song fixtures in
addition to unit tests") isn't satisfied by the synthetic corpus alone.
Coverage is narrower than this project's 9-instrument taxonomy (no toms,
crash, or ride in IDMT), so it complements rather than replaces the
synthetic corpus. Needs: downloading/extracting the dataset separately
(verify its license permits this project's use before committing any of
it or derived fixtures to the repo) and a new benchmark path that feeds
`drumscript.datasets.idmt`'s onsets through this project's own
`app/benchmark.py` metrics (not `drumscript`'s own benchmark CLI, to keep
metrics computed one way across both the synthetic and real corpora).
If IDMT ever proves insufficient on its own, a second, complementary
option remains: synthesizing instrument sounds from short real one-shot
samples (licensed/royalty-free drum hit samples) layered at known times
in this project's own corpus format, giving full 9-instrument coverage
with real transients.

**Deferred:** out of scope for #49 - the corpus as built already satisfies
#45/#46's acceptance criteria (repeatable, labelled, documented tolerance,
multiple groove styles); this entry exists so a future reader doesn't
misread the low absolute F1 number as a DrumScript quality problem.
