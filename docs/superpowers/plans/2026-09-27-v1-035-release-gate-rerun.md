# V1-035 release gate re-run (#86)

**Goal:** re-run `docs/RELEASE_CHECKLIST.md` now that the two blockers (#113
tempo octave, #114 kick detection) are merged, and bring
`docs/RELEASE_REPORT_V1.md` up to date so the product owner can sign off the
v1.0 Definition of Done.

**Scope:** verification and documentation. Code changes only if the pass finds
a defect (stop rule: record, triage with the user; core sync/data-loss defects
block the release).

## Tasks

1. **Clean deployment** (§0): `docker compose -p drumscore-v1035r` with fresh
   volumes on host ports 18000/13000 (the default `drumscore` stack keeps its
   saved CCR project; tear down the throwaway `drumscore-v1037` stack first).
   Record health/readiness.
2. **Automated gate** (§1): full backend pytest (Postgres on :5433), frontend
   Jest, `pnpm lint`, `npx tsc --noEmit`.
3. **Browser pass** (§2) with Playwright on CCR (`bO28lB1uwp4`) and Rick
   Astley (`dQw4w9WgXcQ`); the unavailable ID `aaaaaaaaaaa` for failure →
   retry. Key re-checks versus the 2026-09-25 pass: detected tempo (~115 BPM),
   beamed eighths, kick count, metronome/count-in on quarter notes. Also
   compare CCR against the reference MIDI with `midi_compare.py` (session
   scratchpad copy).
4. **Performance baseline** (§3): stage durations (a new kick detector and
   Beat This! run on every job), peak worker memory via `docker stats`,
   artifact disk, duplicate time, render time, long tasks during playback.
5. **Report**: rewrite `docs/RELEASE_REPORT_V1.md` for the re-run (outcome,
   environment, tables, defects, limitations from the `TECHNICAL_DEBT.md`
   index, DoD mapping). Sign-off stays with the product owner (audible checks).
6. PR "Part of #86"; #86 closes on sign-off.
