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
