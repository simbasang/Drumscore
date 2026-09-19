# Audio Playback Logging & Retries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Player's audio fetch/decode fails, retry transient failures automatically and log enough detail (frontend console + backend logs) that the next occurrence of "Failed to load audio for playback" can actually be diagnosed, instead of being swallowed by a bare `catch {}`.

**Architecture:** `loadAudioBuffer` (frontend/lib/audio/loadAudioBuffer.ts) gains an injectable retry loop with exponential backoff and per-attempt `console.error` logging. `Player.tsx`'s load effect stops swallowing the error and logs it with job/url context before setting `status: "error"`. On the backend, the two audio-serving endpoints in `app/api/jobs.py` get a module logger that records why a request couldn't be served (job not found, file not ready) — this is the only place today with zero logging.

**Tech Stack:** TypeScript/Jest/React Testing Library (frontend, per `C:\Users\sebas\.claude\rules\testing.md`), Python/pytest + FastAPI TestClient + `caplog` (backend).

**Spec:** This session's manual test report — job `d627b43c-467c-41dc-9714-cf7df0bf1998` (`https://www.youtube.com/watch?v=XKOlAYP5ENs`) reached `tempo_mapped`/1315 hits/92 BPM, but the Player showed "Failed to load audio for playback." Investigation (see conversation) confirmed the backend currently serves both stems correctly (200 OK, valid 16-bit PCM WAV, correct content-length) — the failure is not currently reproducible server-side, meaning it was transient/environmental on the frontend side, and the code has no logging to tell us which of {network error, non-2xx response, `decodeAudioData` failure} it was.

## Global Constraints

- Frontend tests: Jest + React Testing Library only, `__tests__` folder beside the file under test, `describe`/`it("should ...")` naming, AAA structure with blank lines between sections (per `C:\Users\sebas\.claude\rules\testing.md`).
- No new npm/pip dependencies — implement retry/backoff and logging with what's already in the stack (native `fetch`, `setTimeout`, Python `logging`).
- Keep the user-facing error message unchanged ("Failed to load audio for playback.", `role="alert"`) — this is a logging/resilience change, not a UX redesign.
- Follow TDD: failing test before implementation, for every step below.

---

### Task 1: Retry with backoff + logging in `loadAudioBuffer`

**Files:**
- Modify: `frontend/lib/audio/loadAudioBuffer.ts`
- Test: `frontend/lib/audio/__tests__/loadAudioBuffer.test.ts`

**Interfaces:**
- Produces: `loadAudioBuffer(url: string, context: DecodableAudioContext, retryOptions？: RetryOptions): Promise<AudioBufferLike>` where
  ```ts
  export interface RetryOptions {
    attempts?: number; // total attempts including the first; default 3
    delayMs?: (attempt: number) => number; // default: 300 * 2 ** (attempt - 1)
    sleep?: (ms: number) => Promise<void>; // default: real setTimeout-based sleep
  }
  ```
  `Player.tsx` (Task 2) consumes `loadAudioBuffer(url, context)` with defaults — it does not need to pass `retryOptions`.

- [ ] **Step 1: Write the failing tests**

Replace the existing "should throw when the fetch response is not ok" test (its old single-attempt assumption no longer holds) and add new retry-specific tests:

```ts
import { loadAudioBuffer, type DecodableAudioContext } from "../loadAudioBuffer";

function fakeContext(decodeAudioData: jest.Mock): DecodableAudioContext {
  return {
    currentTime: 0,
    destination: {},
    createBufferSource: jest.fn(),
    createGain: jest.fn(),
    decodeAudioData,
  } as unknown as DecodableAudioContext;
}

function noopSleep() {
  return Promise.resolve();
}

describe("loadAudioBuffer", () => {
  let consoleErrorSpy: jest.SpyInstance;

  beforeEach(() => {
    consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("should fetch and decode audio data from the given URL", async () => {
    const arrayBuffer = new ArrayBuffer(8);
    const decodedBuffer = { duration: 12.5 };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      arrayBuffer: () => Promise.resolve(arrayBuffer),
    } as unknown as Response);
    const decodeAudioData = jest.fn().mockResolvedValue(decodedBuffer);
    const context = fakeContext(decodeAudioData);

    const result = await loadAudioBuffer("http://localhost:8000/audio.wav", context);

    expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/audio.wav");
    expect(decodeAudioData).toHaveBeenCalledWith(arrayBuffer);
    expect(result).toBe(decodedBuffer);
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it("should retry after a transient failure and succeed without exhausting attempts", async () => {
    const arrayBuffer = new ArrayBuffer(8);
    const decodedBuffer = { duration: 12.5 };
    global.fetch = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        arrayBuffer: () => Promise.resolve(arrayBuffer),
      } as unknown as Response);
    const decodeAudioData = jest.fn().mockResolvedValue(decodedBuffer);
    const context = fakeContext(decodeAudioData);

    const result = await loadAudioBuffer("http://localhost:8000/audio.wav", context, {
      sleep: noopSleep,
    });

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(result).toBe(decodedBuffer);
    expect(consoleErrorSpy).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy.mock.calls[0][0]).toContain("attempt 1/3");
  });

  it("should retry the configured number of attempts then throw the last error", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 } as Response);
    const decodeAudioData = jest.fn();
    const context = fakeContext(decodeAudioData);

    await expect(
      loadAudioBuffer("http://localhost:8000/audio.wav", context, {
        attempts: 3,
        sleep: noopSleep,
      }),
    ).rejects.toThrow("Failed to load audio");

    expect(global.fetch).toHaveBeenCalledTimes(3);
    expect(decodeAudioData).not.toHaveBeenCalled();
    expect(consoleErrorSpy).toHaveBeenCalledTimes(3);
    expect(consoleErrorSpy.mock.calls[2][0]).toContain("attempt 3/3");
  });

  it("should use exponential backoff delays between attempts", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 } as Response);
    const sleep = jest.fn().mockResolvedValue(undefined);

    await expect(
      loadAudioBuffer("http://localhost:8000/audio.wav", fakeContext(jest.fn()), {
        attempts: 3,
        sleep,
      }),
    ).rejects.toThrow();

    expect(sleep).toHaveBeenNthCalledWith(1, 300);
    expect(sleep).toHaveBeenNthCalledWith(2, 600);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx jest lib/audio/__tests__/loadAudioBuffer.test.ts`
Expected: FAIL — `loadAudioBuffer` doesn't accept a third argument yet and never retries/logs.

- [ ] **Step 3: Implement the retry loop**

```ts
import type { AudioBufferLike, AudioContextLike } from "./SyncedPlayer";

export interface DecodableAudioContext extends AudioContextLike {
  decodeAudioData(data: ArrayBuffer): Promise<AudioBufferLike>;
  close(): Promise<void>;
}

export interface RetryOptions {
  attempts?: number;
  delayMs?: (attempt: number) => number;
  sleep?: (ms: number) => Promise<void>;
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function fetchAndDecode(
  url: string,
  context: DecodableAudioContext,
): Promise<AudioBufferLike> {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Failed to load audio: ${url} (status ${response.status})`);
  }

  const arrayBuffer = await response.arrayBuffer();
  return context.decodeAudioData(arrayBuffer);
}

export async function loadAudioBuffer(
  url: string,
  context: DecodableAudioContext,
  retryOptions: RetryOptions = {},
): Promise<AudioBufferLike> {
  const attempts = retryOptions.attempts ?? 3;
  const delayMs = retryOptions.delayMs ?? ((attempt: number) => 300 * 2 ** (attempt - 1));
  const sleep = retryOptions.sleep ?? defaultSleep;

  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetchAndDecode(url, context);
    } catch (error) {
      lastError = error;
      console.error(`[loadAudioBuffer] attempt ${attempt}/${attempts} failed for ${url}:`, error);
      if (attempt < attempts) {
        await sleep(delayMs(attempt));
      }
    }
  }

  throw lastError instanceof Error ? lastError : new Error(`Failed to load audio: ${url}`);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx jest lib/audio/__tests__/loadAudioBuffer.test.ts`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/audio/loadAudioBuffer.ts frontend/lib/audio/__tests__/loadAudioBuffer.test.ts
git commit -m "feat: retry transient audio load failures with backoff and logging"
```

---

### Task 2: Stop swallowing the load error in `Player.tsx`

**Files:**
- Modify: `frontend/components/Player.tsx:71-75`
- Test: `frontend/components/__tests__/Player.test.tsx`

**Interfaces:**
- Consumes: `loadAudioBuffer(url, context)` from Task 1 (called with defaults, no `retryOptions` passed — Player doesn't need to configure retries itself).

- [ ] **Step 1: Write the failing test**

Add to `frontend/components/__tests__/Player.test.tsx`, replacing/augmenting the existing "should show an error message when audio fails to load" test:

```ts
it("should log the underlying error and job id when audio fails to load", async () => {
  const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
  const loadError = new Error("network error");
  (loadAudioBuffer as jest.Mock).mockRejectedValue(loadError);

  render(
    <Player
      apiBaseUrl="http://localhost:8000"
      jobId="job-1"
      events={[]}
      tempoBpm={120}
      createAudioContext={fakeContextFactory}
    />,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(/failed to load audio/i);
  expect(consoleErrorSpy).toHaveBeenCalledWith(
    expect.stringContaining("job-1"),
    loadError,
  );

  consoleErrorSpy.mockRestore();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx jest components/__tests__/Player.test.tsx -t "should log the underlying error"`
Expected: FAIL — `console.error` is never called because the current `catch {}` discards the error.

- [ ] **Step 3: Implement the fix**

In `frontend/components/Player.tsx`, replace:

```ts
      } catch {
        if (!cancelled) {
          setStatus("error");
        }
      }
```

with:

```ts
      } catch (error) {
        if (!cancelled) {
          console.error(`[Player] failed to load audio for job ${jobId}:`, error);
          setStatus("error");
        }
      }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx jest components/__tests__/Player.test.tsx`
Expected: PASS (all tests, including the pre-existing "should show an error message when audio fails to load")

- [ ] **Step 5: Commit**

```bash
git add frontend/components/Player.tsx frontend/components/__tests__/Player.test.tsx
git commit -m "fix: log the real audio load error instead of swallowing it"
```

---

### Task 3: Backend logging on the audio-serving endpoints

**Files:**
- Modify: `backend/app/api/jobs.py`
- Test: `backend/tests/test_jobs_api.py`

**Interfaces:**
- Produces: nothing new is exported; adds a module-level `logger = logging.getLogger(__name__)` used only inside `get_job_drums_audio` and `get_job_accompaniment_audio`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_jobs_api.py` (uses pytest's built-in `caplog` fixture):

```python
def test_get_job_drums_audio_logs_warning_when_job_not_found(caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.jobs"):
        response = client.get("/api/jobs/does-not-exist/audio/drums")

    assert response.status_code == 404
    assert "does-not-exist" in caplog.text


def test_get_job_drums_audio_logs_warning_when_not_ready(caplog):
    job = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=abc12345678"}).json()
    job_id = job["id"]

    with caplog.at_level(logging.WARNING, logger="app.api.jobs"):
        response = client.get(f"/api/jobs/{job_id}/audio/drums")

    assert response.status_code == 409
    assert job_id in caplog.text


def test_get_job_drums_audio_logs_info_on_success(caplog):
    job_id = _create_job_through_to_tempo_mapped()

    with caplog.at_level(logging.INFO, logger="app.api.jobs"):
        response = client.get(f"/api/jobs/{job_id}/audio/drums")

    assert response.status_code == 200
    assert job_id in caplog.text
```

Add the `import logging` at the top of the file alongside the other imports, and check the existing test file for a helper that drives a job through to `tempo_mapped` (the pipeline runs via `background_tasks.add_task`, which `TestClient` executes synchronously) — reuse it instead of `_create_job_through_to_tempo_mapped` if one already exists under a different name; if not, add it near the other fixtures/helpers in this file, modeled on the existing 200-response tests at lines 212 and 223.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_jobs_api.py -k "logs_warning or logs_info" -v`
Expected: FAIL — no logger exists yet in `app/api/jobs.py`, so `caplog.text` is empty and the assertions fail.

- [ ] **Step 3: Implement logging**

In `backend/app/api/jobs.py`, add near the top:

```python
import logging
```

```python
logger = logging.getLogger(__name__)
```

Update the two audio endpoints:

```python
@router.get("/{job_id}/audio/drums")
def get_job_drums_audio(job_id: str, store: JobStore = Depends(get_job_store)) -> FileResponse:
    job = store.get(job_id)

    if job is None:
        logger.warning("Drum audio requested for unknown job %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")

    if job.drums_path is None:
        logger.warning(
            "Drum audio requested for job %s before it was ready (status=%s)",
            job_id,
            job.status.value,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Drum audio not available yet: job status is {job.status.value}",
        )

    logger.info("Serving drum audio for job %s from %s", job_id, job.drums_path)
    return FileResponse(job.drums_path, media_type="audio/wav")


@router.get("/{job_id}/audio/accompaniment")
def get_job_accompaniment_audio(
    job_id: str, store: JobStore = Depends(get_job_store)
) -> FileResponse:
    job = store.get(job_id)

    if job is None:
        logger.warning("Accompaniment audio requested for unknown job %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")

    if job.accompaniment_path is None:
        logger.warning(
            "Accompaniment audio requested for job %s before it was ready (status=%s)",
            job_id,
            job.status.value,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Accompaniment audio not available yet: job status is {job.status.value}",
        )

    logger.info("Serving accompaniment audio for job %s from %s", job_id, job.accompaniment_path)
    return FileResponse(job.accompaniment_path, media_type="audio/wav")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_jobs_api.py -v`
Expected: PASS (all tests, including the three new ones and every pre-existing test in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/jobs.py backend/tests/test_jobs_api.py
git commit -m "feat: log audio endpoint outcomes for diagnosing playback failures"
```

---

## Self-Review Notes

- **Spec coverage:** "add logs" → Task 1 (frontend per-attempt logging), Task 2 (Player logs the real error instead of swallowing it), Task 3 (backend logs why an audio request couldn't be served). "add retrys" → Task 1 (exponential backoff retry in `loadAudioBuffer`). No other requirement was stated.
- **Placeholder scan:** none found — all steps have literal code.
- **Type consistency:** `RetryOptions` defined in Task 1 is the only new type Task 2 depends on indirectly (via `loadAudioBuffer`'s signature), and Task 2 doesn't pass it, so no mismatch risk. Task 3 introduces no new types.
- Task 3's helper `_create_job_through_to_tempo_mapped` is flagged as "reuse if it exists" because the plan author did not exhaustively read `test_jobs_api.py` end to end; the executor must check before adding a duplicate.
