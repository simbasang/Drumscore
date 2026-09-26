# V1-035 (#86) — v1.0 E2E, performance and release gate

**Goal:** prove the v1.0 Definition of Done end to end: an automated API-level lifecycle E2E, a repeatable
release checklist executed in a real browser against a clean container deployment, a measured
performance/resource baseline with a few hard invariants, and a release report with DoD sign-off and
documented limitations.

**Agreed design (brainstorm, 2026-09-25):**
- E2E form: pytest API E2E (real API + real `Worker` + Postgres, fake engines) + scripted browser pass via
  Playwright MCP. No new test framework.
- Performance: measured baseline + hard invariants only (no OOM; disk reclaimed after delete+prune; cache hit
  on duplicate; no main-thread stall during playback).
- Defects found in the browser pass: stop and triage with the user; core sync/data-loss defects block the gate;
  non-core ones become issues/debt entries listed as limitations.

## Task 1 — Automated release E2E (`backend/tests/test_release_e2e.py`)

Marked `pytest.mark.integration`; uses `postgres_store`, `migrated_postgres_url`, `tmp_path`, the
`override(...)` helper pattern from `tests/test_projects_api.py` and fakes from `tests/fakes.py`. Jobs are
processed by a real `Worker(...).run_once()` (not `process_job` directly), so claim/lease/heartbeat are in the path.
These are characterization tests of existing behaviour: after each passes, break one assertion's premise
(e.g. skip the worker run / wrong expected count) once to confirm it can fail.

Tests (key assertions):
1. `test_release_happy_path_submit_process_save_restart_reload`
   - POST project → 201, latest_job `queued`; analysis 409 before processing.
   - `run_once()` → True; GET project → `completed`; analysis 200 with events carrying `source_time`;
     diagnostics 200; `audio/drums` and `audio/accompaniment` bytes served.
   - PUT score (base null) → v1; stale PUT (base null) → 409 with `latest_version` 1.
   - New store from `create_postgres_store(migrated_postgres_url)` + new TestClient (restart): project still
     `completed`, score == v1, analysis equal to pre-restart analysis, a new worker's `run_once()` → False
     (nothing requeued), fake engine call counts unchanged (no reprocessing).
2. `test_release_failure_then_retry_completes`
   - Extractor raises `AudioExtractionError` → job `failed` with `error` set; POST retry → 202 `queued`;
     `run_once()` with healthy engines → `completed`; analysis 200.
3. `test_release_worker_crash_resumes_without_redoing_finished_stages`
   - Transcriber raises a `BaseException` subclass (simulated kill) on worker A; advance clock past lease;
     worker B completes; extractor/separator calls == (1, 1); analysis 200 via API.
4. `test_release_duplicate_reuses_cache_and_delete_reclaims_storage`
   - Completed project; forced duplicate (`?force=true`) processed with fresh fakes → their extractor/separator
     calls == 0 (stage cache hit). DELETE both projects → 204; `prune(...)` → no files left under the
     projects' storage keys (storage dir has no remaining project artifacts).

Run: `uv run pytest tests/test_release_e2e.py -q --tb=short`.

## Task 2 — `docs/RELEASE_CHECKLIST.md`

Repeatable release pass; links to `docs/REGRESSION_CHECKLIST.md` for steps it already covers rather than
duplicating them. Sections: 0 clean deploy (fresh volumes → migrate → readiness, per `DEPLOYMENT.md`, using
`deploy/.env` host ports 18000/13000); 1 automated gate (full suites, lint, tsc, `test_release_e2e.py`);
2 browser pass: submit → progress → render → play → seek (slider + click-on-score) → A/B loop → speed →
count-in/metronome → edit (add/delete/move/change instrument) → undo/redo → save → reload → restart
containers mid-job → duplicate → delete; 3 performance/resource measurements and the four hard invariants,
with how each is measured (structured log `stage_finished` durations, `docker stats`, volume `du`,
`PerformanceObserver` long tasks + score render timing). Each step names automated coverage or "manual only".

## Task 3 — Execute the release pass

Ask the user to stop their dev API/worker first. `docker compose` clean deployment; one real ~3–4 min song;
drive with Playwright MCP; collect measurements. This also executes the Epic 5 manual scenario (debt entry).
On any defect: record reproduction/evidence and STOP for triage.

## Task 4 — `docs/RELEASE_REPORT_V1.md` + doc updates

Results per checklist step (pass/fail + evidence), measured numbers, invariants verdict, DoD table (each PROJECT.md
DoD clause → evidence), known limitations (from the TECHNICAL_DEBT index: no auth/TLS, CPU-only, tempo octave
error, classifier accuracy, dotted/tied durations, etc.). Move "Epic 5's manual practice/correction test was
never run" to `docs/technical-debt-resolved.md` and update the index. Link report + checklist from
`ARCHITECTURE_V1.md` Testing section. Record any new debt.

## Finish

Full suites (`uv run pytest -q --tb=short`, `npx jest --silent --reporters=summary`, lint, `npx tsc --noEmit`),
commit, push, PR (test plan, measured numbers, DoD sign-off pending user confirmation), stop.
