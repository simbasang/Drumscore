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
cd backend && uv run uvicorn app.main:app --reload   # http://localhost:8000
cd frontend && pnpm dev                              # http://localhost:3000
```

## 1. Submit

- [ ] Paste a valid YouTube URL, click "Generate drum score" -> a job is created and its id/status shown immediately.
  Automated: `frontend/components/__tests__/JobForm.test.tsx` (`"should display the created job after a successful submission"`).
- [ ] Submit an empty URL -> inline validation error, no request sent.
  Automated: `JobForm.test.tsx` (`"should show a validation error..."`).
- [ ] Submit an unsupported URL (e.g. a non-YouTube link) -> backend's 422 detail is shown verbatim.
  Automated: `JobForm.test.tsx` (`"should display the backend's error message..."`), `backend/tests/test_jobs_api.py`.

## 2. Process

- [ ] Watch the status line progress through every stage in order: downloading -> downloaded -> separating stems -> transcribing -> mapping tempo -> Done, with the event count and BPM shown once transcribed/done.
  Automated: `JobForm.test.tsx` (`"should poll for job status until it reaches tempo_mapped"`).
- [ ] Kill the backend mid-poll (or block its port) -> after one missed poll, "Lost connection, retrying..." appears; if it stays down, polling stops after 3 consecutive failures and the message changes to a distinct "reload the page" message (not still "retrying...").
  Automated: `JobForm.test.tsx` (`"should keep polling..."`, `"should show a gave-up message..."`). Manual: confirm the browser console also logs `[JobForm] poll attempt N/3 failed...` for each failure.
- [ ] A pipeline stage that fails (e.g. an unreachable video) surfaces the backend's `error` field as an alert, and polling stops.
  Automated: `JobForm.test.tsx` (`"should show the backend's error and stop polling..."`).
- [ ] `GET /api/jobs/{id}/diagnostics` on a `tempo_mapped` job returns one entry per raw transcribed event, each with `source_time`, `measure`/`beat`/`subdivision`, `quantized_time`, and `quantization_error_seconds` — confirms raw transcription -> timing -> score data is inspectable for the same song without touching production state.
  Automated: `backend/tests/test_diagnostics.py`, `backend/tests/test_jobs_api.py` (`test_get_diagnostics_*`).

## 3. Load

- [ ] Once processing reaches "Done", the score renders (percussion staff, all stems up, open/closed hi-hat visually distinct) and "Loading audio..." shows briefly before playback controls appear.
  Automated: `frontend/components/__tests__/DrumScore.test.tsx`, `frontend/components/__tests__/Player.test.tsx` (`"should show a loading state..."`, `"should show playback controls once audio has loaded"`).
- [ ] If audio fails to load, a visible error replaces the controls, and the real underlying error (not a generic message) is logged to the console with the job id.
  Automated: `Player.test.tsx` (`"should show an error message..."`, `"should log the underlying error..."`), `frontend/lib/audio/__tests__/loadAudioBuffer.test.ts` (retry/backoff).

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
| Raw transcription -> timing -> score data can be inspected for the same song | `GET /api/jobs/{id}/diagnostics` (#35): pairs every raw transcribed event with its quantized musical position, reconstructed time, and quantization error, without altering production results — see "Process" section above. |
| Regression baseline exists | The backend (165 tests) and frontend (95 tests) automated suites, plus this checklist, plus `backend/tests/fixtures/` (#34)'s deterministic synthetic diagnostic-song corpus (steady 4/4, intro count-in, dense fill, timing variation) for reproducible timing-case testing going forward. |

Implementation issues: #34, #35, #36, #37, #38 — all merged to `main`.
