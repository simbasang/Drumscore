# Regression checklist

A repeatable manual pass through the current product, covering **submit -> process ->
load -> play -> seek -> mix** — the full path a real user takes. Run this after any
change that touches the pipeline, the player, or the notation renderer, and whenever
a PR claims "full-song manual verification" (see `docs/superpowers/plans/2026-09-20-playhead-jumping.md`
for the concrete procedure this checklist is based on — submit through the real UI
against a real YouTube video, then drive the running page).

Each step names what to check and how, and whether it's already covered by an
automated test (so a reviewer knows what still needs a human/browser pass vs. what a
green test suite already guarantees).

## Setup

```bash
docker compose -f docker-compose.dev.yml up -d          # Postgres (port 5432)
cd backend && uv run uvicorn app.main:app --reload      # API, http://localhost:8000
cd backend && uv run python -m app.worker               # workers (second terminal)
cd frontend && pnpm dev                                 # http://localhost:3000
```

See README "Running locally" and `docs/PERSISTENCE.md` for configuration.

## 1. Submit

- [ ] Paste a valid YouTube URL, click "Generate drum score" -> a project is created and its project page opens immediately (processing has not started yet; the API only enqueues).
  Automated: `frontend/components/__tests__/NewProjectForm.test.tsx` (`"should create a project and open it"`), `backend/tests/test_projects_api.py` (`test_create_enqueues_a_project_without_running_the_pipeline`).
- [ ] Submit an empty URL -> inline validation error, no request sent.
  Automated: `NewProjectForm.test.tsx` (`"should ask for a URL when the field is empty"`).
- [ ] Submit an unsupported URL (e.g. a non-YouTube link) -> backend's 422 detail is shown verbatim.
  Automated: `NewProjectForm.test.tsx` (`"should show the backend error"`), `backend/tests/test_projects_api.py` (`test_create_rejects_unsupported_urls`).
- [ ] Submit the same song again -> the form offers "Open existing"; "Process anyway" creates a second project that reuses the cached stage outputs (the worker log shows no second `running stage extract`).
  Automated: `NewProjectForm.test.tsx` (`"should offer to open the existing project for a duplicate song"`, `"should process a duplicate anyway when asked"`), `backend/tests/test_runner.py` (`test_forced_duplicate_reuses_cached_stage_outputs`, `test_forced_duplicate_after_source_audio_was_pruned_does_not_download_again`).
- [ ] The library on the home page lists the project with its latest status; deleting it (after confirmation) removes it from the list.
  Automated: `frontend/components/__tests__/ProjectLibrary.test.tsx`, `test_projects_api.py` (`test_list_returns_live_projects_with_status`, `test_delete_soft_deletes_and_hides_project`).

## 2. Process

- [ ] On the project page, watch the status line progress through the stages in order: queued -> downloading -> separating stems -> transcribing -> mapping tempo, then the player appears once the job is `completed`.
  Automated: `frontend/components/__tests__/ProjectView.test.tsx` (`"should show progress while processing and the player once completed"`), `backend/tests/test_runner.py`, `backend/tests/test_worker.py`.
- [ ] Stop the API mid-poll (or block its port) -> "Lost connection, retrying..." appears; if it stays down, polling stops after 3 consecutive failures and a distinct "reload the page" alert replaces it.
  Automated: `ProjectView.test.tsx` (`"should retry transient poll errors and give up after three in a row"`). Manual: confirm the browser console logs `[ProjectView] poll N/3 failed for project ...` for each failure.
- [ ] A pipeline stage that fails permanently (e.g. an unreachable video) shows the backend's `error` as an alert with a "Retry processing" button; retrying requeues the job.
  Automated: `ProjectView.test.tsx` (`"should show the failure and requeue on retry"`), `test_projects_api.py` (`test_retry_requeues_failed_job_only`).
- [ ] Press Ctrl+C in the worker terminal while a job is separating stems -> the worker finishes or abandons the stage, the job is not marked failed, and on restart another worker resumes it without re-downloading.
  Automated: `backend/tests/test_worker.py` (`test_stop_during_a_job_releases_the_lease_after_the_current_stage`, `test_stop_that_kills_the_engine_releases_the_lease_and_refunds_the_attempt`), `backend/tests/test_engine_process.py`.
- [ ] `GET /api/projects/{id}/diagnostics` on a completed project returns one entry per raw transcribed event, each with `source_time`, `measure`/`beat`/`subdivision`, `quantized_time`, and `quantization_error_seconds` — confirms raw transcription -> timing -> score data is inspectable for the same song without touching production state.
  Automated: `backend/tests/test_diagnostics.py`, `backend/tests/test_projects_api.py` (`test_diagnostics_before_and_after_completion`).

## 3. Load

- [ ] Once the job is completed, the score renders (percussion staff, all stems up, open/closed hi-hat visually distinct) and "Loading audio..." shows briefly before playback controls appear.
  Automated: `frontend/components/__tests__/DrumScore.test.tsx`, `frontend/components/__tests__/Player.test.tsx` (`"should show a loading state..."`, `"should show playback controls once audio has loaded"`).
- [ ] If audio fails to load, a visible error replaces the controls, and the real underlying error (not a generic message) is logged to the console with the project id.
  Automated: `Player.test.tsx` (`"should show an error message..."`, `"should log the underlying error..."`), `frontend/lib/audio/__tests__/loadAudioBuffer.test.ts` (retry/backoff).
- [ ] Edit the score and save (button or Ctrl/Cmd+S) -> reloading the page (or restarting the API) shows the saved version, not a rebuilt score.
  Automated: `Player.test.tsx` (`"should save the edited score and show it as saved"`, `"should save with Ctrl+S"`), `ProjectView.test.tsx` (`"should load the saved score instead of rebuilding from the analysis"`), `test_projects_api.py` (`test_project_survives_restart_with_saved_edits`).

## 4. Play

- [ ] Press Play: both stems start in sync, the button flips to Pause, and the playhead begins moving.
  Automated: `Player.test.tsx` (`"should play, run a raf tick..."`).
- [ ] Let a multi-row song play through at least one row transition and one dense-measure passage: the playhead never slides backward within a row; it holds and cuts cleanly at row/measure boundaries.
  Automated: `frontend/lib/notation/__tests__/timeline.test.ts`, `DrumScore.test.tsx` (`"should never move the playhead backward..."`). Manual: verified for real in `docs/superpowers/plans/2026-09-20-playhead-jumping.md` against a real processed song.
- [ ] Let playback run to the end of the track: it stops cleanly at the real duration, no runaway `currentTime`, button flips back to Play.
  Automated: `frontend/lib/audio/__tests__/SyncedPlayer.test.ts`, `Player.test.tsx` (`"should flip back to a Play button..."`).

## 5. Seek

- [ ] Drag the seek slider to an arbitrary position: playback (and the playhead) jumps there immediately, both stems stay in sync.
  Automated: `Player.test.tsx` (`"should seek by calling player.seek..."`), `SyncedPlayer.test.ts`.

## 6. Mix

- [ ] Master volume slider changes overall loudness without affecting sync or drum volume.
  Automated: `Player.test.tsx` (`"should set master volume..."`).
- [ ] Drums volume slider at 100% plays the original drums normally; at 0% the drums are completely silent while the accompaniment is unaffected; intermediate values reduce drums only. Changing it never moves playback position.
  Automated: `Player.test.tsx` (`"should set drums volume..."`), `SyncedPlayer.test.ts` (gain-node tests).

## Automated baseline

Full suites, run before every PR (see each PR's description for the count at time of merge):

```bash
cd backend && uv run pytest       # 165 passed as of #38 (V1-005)
cd frontend && pnpm test          # 95 passed as of #38 (V1-005)
cd frontend && pnpm lint          # 0 errors
cd frontend && npx tsc --noEmit   # clean
```

---

## EPIC 1 (#28) exit criteria — status: PASSED

| Exit-gate criterion | Evidence |
|---|---|
| Known runtime defects are reproduced or explicitly classified | **Playhead jumping** (#36): reproduced via live full-song verification against a real processed song, root-caused to two concrete mechanisms (cross-row and cross-measure x-interpolation), fixed, and re-verified live. **AbortError** (#37): classified dev-only with concrete supporting evidence (code reading showing no `AbortController` anywhere and that `Player`'s cleanup never aborts a fetch, plus Next.js's own docs on Fast Refresh/Strict Mode dev-only effect re-invocation) — no production-relevant defect found. |
| Raw transcription -> timing -> score data can be inspected for the same song | `GET /api/jobs/{id}/diagnostics` (#35; now `GET /api/projects/{id}/diagnostics` since Epic 6 Slice A): pairs every raw transcribed event with its quantized musical position, reconstructed time, and quantization error, without altering production results — see "Process" section above. |
| Regression baseline exists | The backend (165 tests) and frontend (95 tests) automated suites, plus this checklist, plus `backend/tests/fixtures/` (#34)'s deterministic synthetic diagnostic-song corpus (steady 4/4, intro count-in, dense fill, timing variation) for reproducible timing-case testing going forward. |

Implementation issues: #34, #35, #36, #37, #38 — all merged to `main`.
