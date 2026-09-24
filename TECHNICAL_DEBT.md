# Technical debt

Things found along the way that are deliberately deferred rather than
fixed on the spot, so they don't get lost. Each entry: what it is, where
it came from, and what fixing it would involve, marked **Deferred** or
**Partially resolved**. Fully resolved entries move to
`docs/technical-debt-resolved.md`.

**Read the index; open only the entries for the area you are changing.**
When you add, resolve or move an entry, update the index too.

## Index

| Entry | Area | Status |
|---|---|---|
| Tempo estimation disagrees with DrumScript's own estimate (1.5x case) | timing | partial |
| Generated notation doesn't look/read quite right yet (classifier accuracy) | transcription | partial |
| No auto-scroll to follow the playhead (vertical scroll) | player UI | partial |
| Diagnostics `quantization_error_seconds` wrong after measure-shift | diagnostics | deferred |
| Benchmark corpus's synthetic audio (validate on IDMT-SMT-Drums) | transcription | deferred |
| `insertHit` cannot create a new measure | score model | deferred |
| Note/rest durations have no dotted or tied values | notation | deferred |
| `BEAMABLE_DURATIONS` must grow with dotted durations | notation | deferred |
| Beam grouping does not beam across an intra-beat rest | notation | deferred |
| `insertHit` out-of-range gap unreachable after Epic 5 | score model | deferred |
| No "accept"/"dismiss flag" for low-confidence hits | editor | deferred |
| `PracticeTransport.playWithCountIn()` has no re-entrancy guard | player | deferred |
| Orphaned stage files | storage | deferred |
| Unbounded score history | persistence | deferred |
| No authentication | API | deferred |
| Pruner delete races stage-cache reuse | worker | deferred |
| Pruner can leak files of projects deleted mid-prune/mid-job | worker | deferred |
| "← All projects" link drops unsaved score edits | frontend | deferred |
| Retry backoff shows stale "in progress" label | frontend | deferred |
| Worker that lost its lease can overwrite new owner's file | worker | deferred |
| Epic 5's manual practice/correction test was never run | QA | deferred |
| Admission limits are advisory under concurrent requests | API | deferred |
| Import-time logging configuration leaks into caplog-based tests | tests | deferred |

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

## Diagnostics `quantization_error_seconds` is wrong for events that trigger the measure-shift

**Found in:** V1-011 final review

`map_tempo` (`backend/app/pipeline/tempo_mapping.py`; `run_tempo_mapping` in
the since-removed `backend/app/job_processor.py` when this was found) shifts every stored
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
measure values. `test_map_tempo_shifts_measures_so_pre_first_beat_events_are_kept`
(`backend/tests/test_tempo_mapping.py`) already uses the offset-beats
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

---

## `insertHit` cannot create a new measure

**Found in:** V1-018 (#51)

`insertHit` (`frontend/lib/score/transformations.ts`, used by both `addHit`
and `moveHit`) only `.map()`s over the *existing* `score.measures` array -
it never grows the array. It matches each existing measure by index against
`position.measure` and leaves every non-matching measure untouched, so
calling `addHit`/`moveHit` with a `position.measure` beyond
`score.measures.length` silently no-ops: nothing is inserted, and no error
is thrown.

This was discovered during this branch's Task 4 (wiring
`consolidateDurations` into `transformations.ts`) when a test tried
`addHit` on a from-scratch empty `Score` (`fromAnalysisEvents([])`, which
has zero measures) and the insert did nothing. It's only reachable from an
empty `Score` - real transcription data via `fromAnalysisEvents` always
produces at least one measure - so it was correctly ruled out of scope for
V1-018, and the affected test was rewritten to seed a real measure first
instead of fixing `insertHit`.

**Fix would involve:** extending `score.measures` up to `position.measure`
(with empty/whole-rest measures for any gap) before mapping, so `insertHit`
can create measures on demand.

**Deferred:** out of scope for V1-018 - not reachable from the current UI,
which always starts from `fromAnalysisEvents` on real transcription data.

---

## Note/rest durations have no dotted or tied values

**Found in:** V1-018 (#51)

`consolidateDurations`/`extendNoteDurations` (`frontend/lib/score/grid.ts`)
only produce the five power-of-two durations (whole/half/quarter/eighth/
sixteenth) - there's no dotted-note or tied-note support. A gap that isn't
a power-of-two-aligned span renders as a note plus leftover rests rather
than a single dotted note - e.g. a kick on beat 1 followed by silence to a
kick on beat 4 renders as [half note, quarter rest, quarter note] rather
than a dotted half note. This is consistent with how the pre-existing
`consolidateRests` already handles rests (same limitation, already accepted
for rests), but it's a newly user-visible behavior now that notes
consolidate too.

**Fix would involve:** extending `DURATION_SIZES_SIXTEENTHS`/the
consolidation algorithm to consider dotted values (1.5x a base duration)
and/or emit tied notes across a gap, rather than only the five untied
power-of-two values.

**Deferred:** out of scope for V1-018 - consistent with the pre-existing
rest-consolidation behavior; revisit if real-groove testing shows this
reads poorly.

---

## `BEAMABLE_DURATIONS` will need to grow in lockstep with dotted-duration support

**Found in:** V1-019 (#52) final review

`BEAMABLE_DURATIONS` (`frontend/lib/notation/beaming.ts`) is a string-exact
`Set(["8", "16"])` that `isBeamable` checks a slot's `duration` against.
It has no knowledge of dotted or tied duration strings - it doesn't need to
today, because "Note/rest durations have no dotted or tied values" (the
V1-018/#51 entry above) means `duration` never currently holds anything
other than `"1"`/`"2"`/`"4"`/`"8"`/`"16"`. But when that debt is eventually
resolved and dotted durations (e.g. `"8d"`/`"16d"`) start appearing,
`BEAMABLE_DURATIONS`'s exact-string membership check will silently exclude
them - a dotted eighth or sixteenth note would render unbeamed (correctly
noteheaded and stemmed, just flagged on its own) instead of beamed with its
neighbors. Not a crash, not even a wrong note - just a quiet notation-quality
regression that's easy to miss because nothing errors.

**Fix would involve:** extending `BEAMABLE_DURATIONS` (or switching
`isBeamable` to a base-duration check that strips a trailing dot marker)
whenever dotted/tied duration values are introduced, in the same change
that introduces them.

**Deferred:** no dotted durations exist yet (see the V1-018/#51 entry
above), so there's nothing to fix today - recorded so the future change
that adds dotted durations doesn't miss this call site.

---

## Beam grouping does not beam across an intra-beat rest

**Found in:** V1-019 (#52) final review

`computeBeamGroupIndices` (`frontend/lib/notation/beaming.ts`) flushes the
current beam group whenever it encounters a rest, even a short rest fully
inside a beat - e.g. an eighth note, a sixteenth rest, then a sixteenth
note, all within one beat, renders as two separate unbeamed/flagged notes
rather than one beam with a stemlet drawn over the rest. This matches the
pre-existing VexFlow call this branch replaced (`Beam.generateBeams` was
invoked with `beamRests: false`), so it isn't a regression introduced by
this branch. But conventional drum engraving often does beam across a
short intra-beat rest (typically rendered as a stemlet), so this is a real,
intentional simplification rather than an oversight, and worth recording as
future engraving-quality work.

**Fix would involve:** allowing `computeBeamGroupIndices` to include a
rest slot inside an otherwise-beamable run (rather than flushing on any
rest), and passing `beamRests: true` (plus VexFlow's stemlet options) to
`Beam` construction in `buildBeams` for groups that contain one.

**Deferred:** not part of V1-019/#52's acceptance criteria (which asked for
conventional beaming of note runs, not rest-spanning beams); revisit if
real-groove testing shows the current unbeamed-around-rests rendering reads
poorly for common drum patterns (e.g. eighth-note-rest-eighth-note
snare/hi-hat figures).

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

---

## No "accept"/"dismiss flag" affordance for low-confidence hits

**Found in:** Epic 5 (V1-023..V1-028) final whole-branch review

Issue #79 (V1-028)'s acceptance criteria describe an "accept/correct" flow
for confidence-flagged hits. The correction editor built in this epic
(`Player.tsx`) gives a user the tools to *correct* a flagged hit (move,
delete, change instrument), but no way to *dismiss the flag without
changing the hit* - `isLowConfidence` (`frontend/lib/score/confidence.ts`)
has no corresponding "reviewed"/"accepted" state to set.

The design spec's own proposed mechanism was to bump a hit's `confidence`
value to clear the flag, which would fabricate a confidence number in
violation of `CLAUDE.md`'s "never fabricate confidence values" rule, so it
was not implemented. The reviewer's alternative - a new `reviewed`/
`accepted` boolean field on `ScoreHit`, propagated through
`useScoreEditor.ts`/`transformations.ts`/`buildStaveNote.ts` - is a real
type change, not a small fix suitable for this epic's single, no-second-wave
final fix round.

Production confidence is null on every real job today (an Epic 3 finding),
so the entire confidence-review UI is already dormant in practice; only the
"dismiss without changing" affordance is missing, not correction itself.

**Fix would involve:** adding a `reviewed: boolean` (or similar) field to
`ScoreHit`, a `markReviewed`/`acceptHit` action in `useScoreEditor.ts`, and
an "Accept" button in the correction editor next to already-flagged hits
that suppresses `isLowConfidence`'s styling once set - without ever writing
to `confidence` itself.

**Deferred:** explicitly scoped out of Epic 5's PR; the existing move/
delete/change-instrument tools remain sufficient to correct a flagged hit
in the meantime. Revisit once a real transcription pipeline populates
non-null confidence values (today, nothing exercises this UI outside a
synthetic test fixture).

---

## `PracticeTransport.playWithCountIn()` has no re-entrancy guard

**Found in:** Epic 5 (V1-023..V1-028) final review's scoped re-review

`playWithCountIn()` stores its pending `setTimeout` handle in
`countInTimeoutId` and `pause()` clears it, closing the bug where an
in-flight count-in could fire `play()` after unmount closed the
`AudioContext`. But `playWithCountIn()` itself has no guard against being
called a second time before a first pending timer fires: a second call
unconditionally overwrites `countInTimeoutId` without clearing the prior
handle, so the first timer leaks and could still fire `play()` after a
*later* `pause()` (which now only cancels the second, most recent handle).

Not currently reachable: `Player.tsx`'s Count-in button is
`disabled={isCountingIn || isPlaying}`, set synchronously the moment
`handleCountInPlay` runs, and it's the sole call site of
`playWithCountIn()` in the app - so no existing caller can trigger the
double-call.

**Fix would involve:** clearing any existing `countInTimeoutId` at the top
of `playWithCountIn()` before scheduling a new one, the same defensive
pattern `pause()` already uses.

**Deferred:** parked by the final review's adjudication (single allowed fix
wave already spent) since no live caller can reach it; revisit only if a
future caller invokes `playWithCountIn()` without the existing UI-level
guard.

---

## Orphaned stage files

**Found in:** Epic 6 Slice A

A crash between `storage.put` (which writes and renames a stage's output file
into place) and `commit_stage` (which writes the corresponding `artifacts` row
in the same transaction as the job's status and cache entry) leaves a file at
the job's storage key with no database row referencing it. `_run_stages`'s
next run of the same job re-derives the same key and overwrites it via
`storage.put`, so a job that eventually succeeds or is retried cleans up after
itself. But a job that is *never* retried (e.g. deliberately abandoned, or one
whose project is soon after soft-deleted before that stage's job ever runs
again) leaks that file: the pruner's `disposable_storage_keys` only considers
keys that have an `artifacts` row, so an orphaned file with no row is invisible
to it and stays on disk until someone cleans storage manually.

**Fix would involve:** either writing a provisional `artifacts` row before
`storage.put` (marked pending until `commit_stage` confirms it, so the pruner
can find and remove it if the job never resumes), or a separate orphan sweep
that lists storage keys under `projects/<project_id>/<job_id>/` with no
matching `artifacts` row for jobs whose project is deleted or whose job is
long-abandoned.

**Deferred:** narrow window (a crash in the few instructions between the
storage write and the transaction commit), self-healing on any retried job,
and no user-visible impact — recorded so unexplained storage growth on
never-retried jobs doesn't get mis-diagnosed later.

---

## Unbounded score history

**Found in:** Epic 6 Slice A

`score_versions` keeps every save as its own row (`PostgresStore.save_score`
always inserts, never overwrites) with no cap on row count and no compaction of
old versions. A project edited many times over its lifetime accumulates one
row per save indefinitely.

**Fix would involve:** a retention policy for old score versions (e.g. keep
the latest N, or collapse versions older than some age into a single
snapshot), applied either by the pruner or a separate maintenance pass, being
careful not to break `base_version` optimistic-concurrency checks for any
save still in flight against an older version.

**Deferred:** out of scope for Epic 6 Slice A; score JSON is small relative to
audio/stem artifacts, so this is a slow-growing concern rather than an urgent
one — revisit if a long-lived project's version count becomes a real problem.

---

## No authentication

**Found in:** Epic 6 Slice A

v1 has no authentication or authorization anywhere in the API. It relies
entirely on deployment-level access control (private network / reverse-proxy
auth) to keep it from being reachable by anyone but its intended user. Anyone
who can reach the API can list, create, retry and delete any project —
including `DELETE /api/projects/{id}`, which soft-deletes (and, after the next
prune, permanently purges) another user's work.

**Fix would involve:** adding an auth layer (API keys, session auth, or
similar) in front of the projects router, plus per-project ownership checks,
before this is ever deployed somewhere it isn't already behind a private
network or reverse-proxy auth.

**Deferred:** out of scope for Epic 6 Slice A; acceptable for the current
single-user, privately-deployed use case; must be resolved before any
production deployment reachable by more than one trusted party.

---

## Pruner delete races stage-cache reuse

**Found in:** Epic 6 Slice A (pruner, `backend/app/worker/pruner.py`)

`prune()` computes `disposable_storage_keys` and deletes each key's file in a
separate step from marking its `artifacts` rows pruned
(`store.mark_storage_keys_pruned`), all under the maintenance advisory lock —
but the advisory lock only serializes against *other prune runs*, not against
a worker concurrently running a pipeline stage. A worker's `_obtain` reads a
`stage_cache` entry, finds `ctx.storage.exists(a.storage_key)` true, and
reuses that key (creating a new `artifacts` row pointing at it, see
`docs/PERSISTENCE.md` §6) with no lock held between that existence check and
its own later `commit_stage`. If the pruner's disposability query ran (and
found that key disposable under the *old* set of referencing rows) just
before the worker's cache hit, and the pruner's `storage.delete(key)` for that
key executes after the worker's existence check but before the worker's
`commit_stage`, the worker's new row ends up pointing at a file that no longer
exists — a silent loss of the reused artifact, not caught until something
later tries to read it (e.g. `GET /api/projects/{id}/audio/{stem}`, which does
check `storage.exists` and would correctly 410, or the next pipeline stage
reading the file, which would error).

**Fix would involve:** re-checking each key's disposability inside the same
transaction (or under the same lock) as its delete, so a worker's
cache-hit-driven new row is guaranteed to be visible to the disposability
check before the file can be removed — e.g. moving the existence-check-and-
claim into one transaction, or having the pruner re-verify disposability
immediately before each individual `storage.delete` call rather than only
once at the start of the run.

**Deferred:** narrow race window (requires a prune run and a cache-hit stage
claim on the same key to interleave within the run), no reproduction yet —
recorded per Epic 6 Slice A wrap-up so it isn't lost before Slice B/C's
production hardening work picks it up.

---

## Pruner can leak files of projects deleted during a prune or a running job

**Found in:** Epic 6 Slice A final review

Two ways a soft-deleted project's files outlive its rows:

1. `prune()` (`backend/app/worker/pruner.py`) takes its disposable keys from
   `disposable_storage_keys` and only later calls `purge_deleted_projects`.
   A project soft-deleted between those two calls has its rows (including
   its `artifacts` rows) purged, but its files were never in the disposable
   set, so they stay on disk with nothing referencing them.
2. The runner checks for deletion only once, before the first stage
   (`process_job` in `backend/app/pipeline/runner.py`). A job whose project is
   deleted while it runs keeps processing, and can write stage files after
   the pruner has already purged the project's rows, again leaving files no
   row points at.

**Fix would involve:** taking a purge snapshot time before the disposable
query and purging only projects deleted before it (so every purged project's
files were in that run's disposable set), plus a deletion check in the
runner's `_checkpoint` so a job stops (and fails as "Project was deleted")
between stages once its project is gone.

**Deferred:** needs a delete to land inside a prune run or a running job;
the orphaned files are invisible to users and only cost disk space.
Recorded with the related "Orphaned stage files" entry so storage growth
isn't mis-diagnosed.

---

## "← All projects" link drops unsaved score edits without a warning

**Found in:** Epic 6 Slice A final review

The project page (`frontend/app/projects/[id]/page.tsx`) links back to the
library with a Next `<Link>`. The unsaved-changes warning is a
`beforeunload` handler, which only fires for full page unloads (reload,
closing the tab, typing a URL), not for client-side navigation, so clicking
the link discards unsaved edits silently.

**Fix would involve:** a navigation guard for client-side navigation while
the score is dirty (intercepting the link click and asking for confirmation,
or disabling/relabelling the link while there are unsaved changes).

**Deferred:** Save and Ctrl/Cmd+S are explicit and the unsaved indicator is
visible; recorded for the next frontend pass.

---

## Retry backoff shows a stale "in progress" label and hides the error

**Found in:** Epic 6 Slice A final review

While a job waits out a transient-error backoff (`schedule_retry` keeps its
last in-progress status and sets `error` and a future `available_at`),
`ProjectView.tsx` shows the status label for that last in-progress status
(e.g. "Separating drum stems...") and only shows `job.error` once the job is
`failed`. The user sees what looks like live progress, with no hint that the
stage failed and will be retried.

**Fix would involve:** returning `available_at` (or a derived "retrying at"
field) in the job summary and showing "Retrying after an error: ..." with the
error while `error` is set on a non-terminal job.

**Deferred:** cosmetic; the job does recover (or fail visibly) on its own.

---

## A worker that lost its lease can overwrite the new owner's stage file

**Found in:** Epic 6 Slice A final review

In `_obtain` (`backend/app/pipeline/runner.py`), `storage.put` (and, for the
extract stage, `set_project_title`) runs before `commit_stage` checks the
lease. Storage keys are deterministic per job
(`projects/<project_id>/<job_id>/<file>`), so a worker whose lease has
already passed to another worker can still rename its output over the file
the new owner wrote or committed for the same stage, before its own
`commit_stage` raises `LeaseLostError`.

**Fix would involve:** checking the lease immediately before `storage.put`
(still racy, but narrower), or making keys unique per attempt (e.g. include
the claim's attempt number or a random suffix) so two owners never write the
same key and the committed row always points at the committing owner's file.

**Deferred:** self-limited: the stale worker's heartbeat sets `lost` and it
abandons at its next checkpoint, both owners run the same deterministic
engines on the same input, and a lease is only lost after a stall longer than
`LEASE_SECONDS`.

---

## Epic 5's manual practice/correction test was never run

**Found in:** GitHub cleanup after PR #109 (2026-09-24)

PR #108 (Epic 5, V1-023..V1-028) was merged with the manual item in its
test plan still unchecked: *generate a song, set an A/B loop, change speed,
enable count-in and metronome, correct a hit, then undo and redo*. Epic 5
(#32) and its issues #74-#79 are closed on the strength of the automated
suites alone (frontend 253/253, backend 222/222 at merge time).

That leaves a gap: the practice transport's Web Audio scheduling (loop
restart, rate changes, metronome/count-in timing) and the correction
editor's interaction with the rendered score have not been checked end to
end in a real browser against real audio. Earlier epics showed that jsdom
tests miss real-browser rendering and timing defects (see the V1-019 beam
and V1-022 clipping findings).

**Fix would involve:** running the manual scenario above against a real
generated song in a browser, confirming stems stay in sync through loop,
seek and rate changes, that metronome clicks and count-in land on the beat,
and that edits and undo/redo update the score and playback correctly;
filing issues for anything that fails.

**Deferred:** do this before release, at the latest as part of V1-035
(#86, v1.0 E2E, performance and release gate).

---

## Admission limits are advisory under concurrent requests

**Found in:** V1-033 (#84)

`_admit_new_job` (`backend/app/api/projects.py`) reads
`Store.live_artifact_bytes()`/`Store.count_active_jobs()` and only then lets
`POST /api/projects`/`POST /api/projects/{id}/retry` insert a new job, with
no lock spanning the read and the write. Two requests that both read a
count/usage just under the limit can both be admitted, so `MAX_ACTIVE_JOBS`
and `STORAGE_MAX_BYTES` can briefly be overshot by the number of concurrent
admitting requests.

**Fix would involve:** a serializable transaction or an explicit lock (e.g.
a Postgres advisory lock, or `SELECT ... FOR UPDATE` on a counter row)
spanning the read-and-decide-and-insert sequence, so concurrent admissions
serialize against each other.

**Deferred:** overshoot is bounded by the number of concurrent requests, and
v1 is a single-user, privately-deployed API (see "No authentication") where
that number is small; revisit if concurrent submission volume grows.

---

## Import-time logging configuration leaks into caplog-based tests

**Found in:** V1-033 (#84) Task 5

`app/main.py` calls `configure_logging()` at import time, which sets the
root logger's level globally for the process. Any caplog-based test whose
own logging setup happens outside its `caplog.at_level` block, in a test
session that has imported `app.main` (directly or transitively), can see
log records leak in from that global root level. Task 5 worked around one
instance of this with an explicit `caplog.set_level(logging.WARNING,
logger="app.pipeline.runner")` in
`test_reused_stages_log_a_cached_finish_without_a_start`.

**Fix would involve:** either an autouse fixture that resets logger levels
per test, or moving `configure_logging()` out of module import time and into
the app factory/lifespan so importing `app.main` alone has no logging
side effect.

**Deferred:** test hygiene only; no production effect.
