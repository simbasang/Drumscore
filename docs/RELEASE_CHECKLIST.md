# Release checklist

The v1.0 release gate (V1-035): a repeatable pass over a **clean deployment**
covering submit → process → render → play → seek → loop → speed → edit → save →
reload, plus failure/restart behaviour and a performance/resource baseline.
Run it before every release and record the outcome in a release report
(`docs/RELEASE_REPORT_V1.md` for v1.0).

Per-step automated coverage for submit/process/load/play/seek/mix is listed in
`docs/REGRESSION_CHECKLIST.md`; this checklist names only what that file
doesn't. **Manual** marks a step that no automated test covers: jsdom can't see
real Web Audio timing or rendered geometry.

**Stop rule:** a failed step is recorded (reproduction, evidence) and the pass
stops for triage. Core playback-sync or data-loss defects block the release;
other defects become issues/`TECHNICAL_DEBT.md` entries and are listed as
known limitations in the report.

## 0. Clean deployment

Follow `docs/DEPLOYMENT.md` §2–§4 from nothing. If development servers already
use 8000/3000, set `API_PORT`/`FRONTEND_PORT` and the matching `PUBLIC_*_URL`s
in `deploy/.env` (e.g. 18000/13000). Stop any development worker pointed at
another database first; it can't claim the stack's jobs, but it does compete
for CPU.

- [ ] `docker compose -f deploy/docker-compose.yml down -v` (fresh volumes), then `build` and `up -d`.
- [ ] `ps`: postgres, api, worker, frontend `healthy`; migrate `Exited (0)`.
- [ ] `GET /api/health` 200; `GET /api/ready` 200 `ready`; `docker compose exec worker python -m app.readiness worker` exits 0.
- [ ] The frontend loads at `PUBLIC_FRONTEND_URL` with an empty library; the browser console has no errors.

## 1. Automated gate

- [ ] `cd backend && uv run pytest -q --tb=short`: all pass (includes `tests/test_release_e2e.py`: API lifecycle, failure → retry, worker-crash resume, duplicate cache reuse, delete + prune reclaiming storage, all against Postgres).
- [ ] `cd frontend && npx jest --silent --reporters=summary`, `pnpm lint`, `npx tsc --noEmit`: clean.

## 2. Browser pass (one real song, ~3–4 min, steady groove)

**Submit and process**
- [ ] Submit the YouTube URL. The project page opens and the status line walks through the stages to completion (REGRESSION_CHECKLIST §1–2). Record the wall-clock processing time.
- [ ] Notation renders: five-line percussion staff, all stems up, simultaneous hits aligned, open/closed hi-hat distinct, mixed durations (not all sixteenths), line breaks adapting to density. **Manual** (rendered geometry).

**Play, seek and mix**
- [ ] Play: both stems start together; the playhead tracks the audible drums through at least two row changes. **Manual** (audible sync).
- [ ] Drums volume at 0% mutes only the drums; at 50% it reduces them; position never moves (REGRESSION_CHECKLIST §6).
- [ ] Seek slider: jumps immediately, stems stay in sync.
- [ ] Click a note on the score: playback jumps to that hit's source time and the playhead lands on the clicked note. **Manual.**

**Practice tools**
- [ ] A/B loop: `Set loop start` → play → `Set loop end` a few bars later. Playback restarts at A at least 3 times with no drift between stems and no audible gap longer than a click. `Clear loop` resumes normal playback. **Manual** (Web Audio scheduling).
- [ ] Playback speed 0.5× and 0.75× with the loop active: pitch/tempo change on both stems together, the playhead stays on the audible notes, and back at 1× nothing has drifted. **Manual.**
- [ ] Metronome on: clicks land on the audible beats (including after a seek and at 0.75×). **Manual.**
- [ ] `Count-in`: four clicks at the local beat period (from the tempo map at the current position), then playback starts from that position one beat after the last click; Play is disabled while it counts. **Manual.**

**Correction editor**
- [ ] Select a hit and `Delete hit`, `Change instrument`, `Move hit`; `Add hit` at a position. Each change re-renders the score immediately and "Unsaved changes" appears. **Manual** (rendered result).
- [ ] `Undo` steps back through all four changes and `Redo` re-applies them, with the score matching each step.
- [ ] Playing after edits: the playhead still follows the audio (edited notes keep their source-time links; added hits map to their musical position).
- [ ] Save (button and Ctrl/Cmd+S): "All changes saved".

**Persistence**
- [ ] Reload the page: the edited score (not a rebuilt one) and the audio load without reprocessing; the worker log shows no new job.
- [ ] `docker compose restart api worker`, then reload: the same result.
- [ ] `docker compose down && up -d` (volumes kept): the library still lists the project with its edits.

**Failure, retry and restart**
- [ ] Submit an unavailable video: the job fails with a readable error and `Retry processing`; retry requeues it (it fails again, cleanly).
- [ ] Submit a second song and `docker compose restart worker` while it is separating stems: the stopping worker releases its lease (`job_finished` outcome `abandoned`), the restarted worker resumes at the first unfinished stage (no second download in the log) and the job completes.
- [ ] Stop the worker (so a job stays queued), open its page, then stop the API: "Lost connection, retrying..." appears, and after 3 failed polls the "reload the page" alert replaces it (the console logs `poll N/3 failed`). Start the API and reload: the page shows the job again. Start the worker.
- [ ] Resubmit the first song: "Open existing" is offered; "Process anyway" completes quickly from the stage cache (log: `stage_finished` with `outcome: "cached"`).
- [ ] Delete a project: it disappears from the library, and after the next prune its files are gone from the `storage` volume.

## 3. Performance and resource baseline

Record every number in the release report; only the four **invariants** gate
the release.

| Measure | How |
|---|---|
| Processing time per stage and total | Worker JSON logs: `stage_finished.duration_ms` per stage, `job_finished.duration_ms` (`docs/OPERATIONS.md` §5). |
| Peak worker memory | `docker stats` sampled during separation/transcription (peak `MEM USAGE`). |
| Artifact disk per project | `du` of the project's directory in the `storage` volume after completion (and after the post-completion source-audio prune). |
| Duplicate reprocessing time | `job_finished.duration_ms` for the "Process anyway" duplicate. |
| Score render time | In the browser: time from the analysis response to the score's SVG in the DOM (`performance.now()` around the render, or the Performance panel). |
| Main-thread stalls during playback | `PerformanceObserver({type: "longtask"})` over 30 s of playback, with the loop and metronome on. |

**Invariants**
- [ ] No OOM or container restart during processing (`docker compose ps` restart count, `docker stats` peak below the container/host limit).
- [ ] Storage is reclaimed: after delete + prune the deleted project's artifacts are gone (automated: `test_release_duplicate_reuses_cache_and_delete_reclaims_storage`).
- [ ] The duplicate is served from the stage cache: no extract/separate/transcribe engine run (automated: same test).
- [ ] No main-thread stall during playback: no long task ≥ 200 ms while playing, and the playhead never visibly freezes.

## 4. Sign-off

Map each clause of the v1.0 Definition of Done (`PROJECT.md`) to its evidence
from sections 1–3, list known limitations (from the `TECHNICAL_DEBT.md`
index), and have the product owner sign off in the release report.
