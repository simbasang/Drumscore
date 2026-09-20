# Job Polling Hardening & Stabilization Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `JobForm`'s job-status polling up to the same reliability/observability standard `loadAudioBuffer` already has (PR #27), fix a real UI bug where a definitive give-up still claims to be "retrying," and produce the regression checklist + Epic 1 exit-criteria writeup the issue asks for.

**Root cause / gap analysis (completed before writing this plan):**

Reading `frontend/components/JobForm.tsx`'s `startPolling`:
```tsx
} catch {
  consecutiveFailures.current += 1;
  if (consecutiveFailures.current >= MAX_CONSECUTIVE_POLL_FAILURES) {
    stopPolling();
  } else {
    setConnectionIssue(true);
  }
}
```
Two concrete gaps, found by tracing the actual state transitions, not guessed:

1. **"Definitive failures stop appropriately" is violated.** `setConnectionIssue(true)` runs on failures 1 and 2 (of 3), showing "Lost connection, retrying...". On failure 3, only `stopPolling()` runs — `connectionIssue` is never reset or given a distinct "gave up" state. Polling genuinely stops, but the UI keeps claiming "retrying..." forever. The existing test `"should stop polling after several consecutive failures"` only asserts `getJob` stops being called; it never asserts what message the user is left looking at, so this gap has no regression coverage today.
2. **"Logs are useful" is not met.** The catch block above discards the error entirely (`catch { ... }`, not even bound to a variable) — nothing is logged. Compare `loadAudioBuffer` (`frontend/lib/audio/loadAudioBuffer.ts`), which logs every attempt: `console.error(\`[loadAudioBuffer] attempt ${attempt}/${attempts} failed for ${url}:\`, error)`. Polling has no equivalent.

On the backend, `GET /api/jobs/{job_id}` (`backend/app/api/jobs.py`) logs nothing for an unknown job, unlike its sibling `GET /api/jobs/{job_id}/audio/drums`, which already logs a warning in the same situation (`logger.warning("Drum audio requested for unknown job %s", job_id)`). Polling an unknown job (e.g. after a backend restart drops in-memory state) currently leaves no trace in the logs.

**What is already correct and stays unchanged:** "transient failures retry with visible state" already works (`"Lost connection, retrying..."` on failures 1-2, and the existing test `"should keep polling and show a reconnecting message after a single transient failure"` covers it). `MAX_CONSECUTIVE_POLL_FAILURES = 3` already matches `loadAudioBuffer`'s default `attempts = 3`. Polling deliberately does **not** get `loadAudioBuffer`'s per-attempt exponential backoff — it's a continuous status poll on a fixed `POLL_INTERVAL_MS`, a different (and already-idiomatic) shape from a one-shot resource fetch's retry loop; the goal is matching `loadAudioBuffer`'s *standard* (retry, log, stop, tell the user), not literally the same code shape. `loadAudioBuffer` itself does not distinguish failure causes (e.g. a 404 is retried identically to a network error) — so polling matching that same standard means also *not* adding new response-code-aware branching, to avoid exceeding what "the same standard as audio loading" actually means.

**Tech Stack:** TypeScript/Jest/React Testing Library (frontend), Python/pytest (backend) - existing stacks, no new dependencies.

**Spec:** GitHub issue #38 (V1-005), the last implementation issue for EPIC 1 (#28).

## Global Constraints

- Match `loadAudioBuffer`'s existing standard (retry with visible state, log every failed attempt, stop and tell the user when giving up) - do not exceed it with new behavior (e.g. status-code-aware branching) it doesn't itself have.
- Keep `POLL_INTERVAL_MS` / `MAX_CONSECUTIVE_POLL_FAILURES` semantics unchanged; only add the missing logging and the missing "gave up" UI state.
- No changes to `TECHNICAL_DEBT.md` (it currently has unrelated local uncommitted edits in progress) - record the regression checklist and Epic 1 exit-criteria writeup in new, dedicated docs instead.

---

### Task 1: Frontend — log every failed poll attempt and show a distinct give-up message

**Files:**
- Modify: `frontend/components/JobForm.tsx`
- Test: `frontend/components/__tests__/JobForm.test.tsx`

**Interfaces:**
- No prop/exported-API changes to `JobForm`. Adds one new internal state (`pollingGaveUp: boolean`) and a `console.error` call inside the existing poll interval callback.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/components/__tests__/JobForm.test.tsx`, inside the `describe("polling", ...)` block, after `"should stop polling after several consecutive failures"`:

```tsx
    it("should show a gave-up message instead of 'retrying' once polling stops after consecutive failures", async () => {
      const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
      (createJob as jest.Mock).mockResolvedValue({
        id: "job-1",
        url: "https://youtu.be/dQw4w9WgXcQ",
        status: "queued",
      });
      (getJob as jest.Mock).mockRejectedValue(new Error("network down"));

      render(<JobForm apiBaseUrl="http://localhost:8000" />);
      fillAndSubmit("https://youtu.be/dQw4w9WgXcQ");
      await act(async () => {});

      await act(async () => {
        jest.advanceTimersByTime(2000);
        jest.advanceTimersByTime(2000);
        jest.advanceTimersByTime(2000);
      });

      expect(screen.queryByText(/lost connection, retrying/i)).not.toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(/lost connection to the server/i);

      consoleErrorSpy.mockRestore();
    });

    it("should log each failed poll attempt with the job id and underlying error", async () => {
      const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
      const pollError = new Error("network blip");
      (createJob as jest.Mock).mockResolvedValue({
        id: "job-1",
        url: "https://youtu.be/dQw4w9WgXcQ",
        status: "queued",
      });
      (getJob as jest.Mock)
        .mockRejectedValueOnce(pollError)
        .mockResolvedValueOnce({ id: "job-1", status: "separating_stems" });

      render(<JobForm apiBaseUrl="http://localhost:8000" />);
      fillAndSubmit("https://youtu.be/dQw4w9WgXcQ");
      await act(async () => {});

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining("job-1"), pollError);

      consoleErrorSpy.mockRestore();
    });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && pnpm test -- JobForm.test.tsx -t "gave-up|log each failed poll"`
Expected: FAIL - `getByRole("alert")` doesn't find the give-up message (none exists yet), and `consoleErrorSpy` was never called.

- [ ] **Step 3: Implement the fix**

In `frontend/components/JobForm.tsx`, add the new state next to `connectionIssue`:

```tsx
  const [connectionIssue, setConnectionIssue] = useState(false);
  const [pollingGaveUp, setPollingGaveUp] = useState(false);
```

Update `startPolling` to reset the new state and log/branch correctly:

```tsx
  function startPolling(jobId: string) {
    stopPolling();
    consecutiveFailures.current = 0;
    setConnectionIssue(false);
    setPollingGaveUp(false);
    pollHandle.current = setInterval(async () => {
      try {
        const updated = await getJob(apiBaseUrl, jobId);
        consecutiveFailures.current = 0;
        setConnectionIssue(false);
        setJob(updated);
        if (TERMINAL_STATUSES.includes(updated.status)) {
          stopPolling();
        }
        await fetchAnalysisIfReady(jobId, updated.status);
      } catch (error) {
        consecutiveFailures.current += 1;
        console.error(
          `[JobForm] poll attempt ${consecutiveFailures.current}/${MAX_CONSECUTIVE_POLL_FAILURES} failed for job ${jobId}:`,
          error,
        );
        if (consecutiveFailures.current >= MAX_CONSECUTIVE_POLL_FAILURES) {
          setConnectionIssue(false);
          setPollingGaveUp(true);
          stopPolling();
        } else {
          setConnectionIssue(true);
        }
      }
    }, POLL_INTERVAL_MS);
  }
```

Add the give-up message to the render output, next to the existing `connectionIssue` paragraph:

```tsx
      {connectionIssue && <p>Lost connection, retrying...</p>}
      {pollingGaveUp && (
        <p role="alert">
          Lost connection to the server. Status may be out of date — reload the page to check
          again.
        </p>
      )}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && pnpm test -- JobForm.test.tsx`
Expected: PASS (all tests in the file, including every pre-existing polling test - no regressions).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/JobForm.tsx frontend/components/__tests__/JobForm.test.tsx
git commit -m "fix: log failed job-status polls and stop claiming to retry once given up"
```

---

### Task 2: Backend — log unknown-job requests to `GET /api/jobs/{job_id}`

**Files:**
- Modify: `backend/app/api/jobs.py`
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- No response/behavior change (still 404) - only adds a `logger.warning` call, matching the existing pattern already used by `get_job_drums_audio`/`get_job_accompaniment_audio`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_jobs_api.py`, near `test_get_job_returns_404_for_unknown_id`:

```python
def test_get_job_logs_warning_when_job_not_found(caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.jobs"):
        response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
    assert any(
        record.name == "app.api.jobs"
        and record.levelno == logging.WARNING
        and "does-not-exist" in record.getMessage()
        for record in caplog.records
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v -k logs_warning_when_job_not_found`
Expected: FAIL - `test_get_job_logs_warning_when_job_not_found` finds no matching warning record (`test_get_job_drums_audio_logs_warning_when_job_not_found` should still pass, unaffected).

- [ ] **Step 3: Implement the fix**

In `backend/app/api/jobs.py`, update `get_job`:

```python
@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, store: JobStore = Depends(get_job_store)) -> JobResponse:
    job = store.get(job_id)

    if job is None:
        logger.warning("Job status requested for unknown job %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse.from_job(job)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_jobs_api.py -v`
Expected: PASS (all tests in the file, no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: log unknown-job requests to GET /api/jobs/{id}"
```

---

### Task 3: Regression checklist and Epic 1 exit-criteria writeup

**Files:**
- Create: `docs/REGRESSION_CHECKLIST.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Run the full test suites one more time to have current, accurate numbers for the writeup**

Run: `cd backend && uv run pytest -q` and `cd frontend && pnpm test` — record the pass counts.

- [ ] **Step 2: Write the checklist**

Create `docs/REGRESSION_CHECKLIST.md` covering, at minimum, one manual pass through **submit -> process -> load -> play -> seek -> mix** (the exact sequence named in the issue), each step naming what to check and how, plus automated-coverage pointers so a reviewer knows what's already guarded by tests vs. what still needs a human/browser pass. Base the "load/play/seek" steps on the concrete verification procedure already exercised for real in `docs/superpowers/plans/2026-09-20-playhead-jumping.md` (submit via UI, poll `GET /api/jobs/{id}` for `tempo_mapped`, then drive the real page). Include an "Epic 1 exit criteria" section mapping each of #28's three exit-gate bullets to the concrete PR/artifact that satisfies it:
- "known runtime defects are reproduced or explicitly classified" -> #36 (playhead jumping: reproduced, root-caused, fixed) and #37 (AbortError: classified dev-only with documented evidence).
- "raw transcription -> timing -> score data can be inspected for the same song" -> #35's `GET /api/jobs/{id}/diagnostics` endpoint.
- "regression baseline exists" -> the full backend (164+) and frontend (93+) automated suites plus this checklist's manual pass.

- [ ] **Step 3: Commit**

```bash
git add docs/REGRESSION_CHECKLIST.md
git commit -m "docs: add regression checklist and document EPIC 1 exit criteria as passed"
```

---

## Self-Review Notes

- **Spec coverage:** "Transient failures retry with visible state" -> already true, unchanged, still covered by the pre-existing test. "definitive failures stop appropriately" -> Task 1's `pollingGaveUp` state + test. "logs are useful" -> Task 1 (frontend poll logging) + Task 2 (backend unknown-job logging). "regression checklist covers submit/process/load/play/seek/mix" -> Task 3. "Epic 1 exit criteria are documented as passed" -> Task 3's dedicated section.
- **Scope check:** deliberately did not add HTTP-status-aware branching (e.g. treating 404 differently from a network error) to polling, since `loadAudioBuffer` - the explicit standard this issue asks to match - does not do that either; adding it would exceed the stated goal ("bring... to the same standard as audio loading"), not just meet it.
