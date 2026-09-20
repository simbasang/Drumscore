# AbortError Investigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify the `AbortError: The operation was aborted.` seen during manual testing (dev-only vs. production-relevant), and close the one real gap the investigation can improve: regression coverage proving the existing error-suppression logic in `Player.tsx` never hides a genuine failure.

**Root cause investigation (completed before writing this plan):**

- `grep -r "AbortController\|AbortSignal" frontend/` returns zero matches — the application never constructs an abort signal or passes one to `fetch()`. Nothing in our own code can directly cause a `fetch()`-level `AbortError`.
- `Player.tsx`'s loading effect's cleanup function does not call `.abort()` on anything:
  ```ts
  return () => {
    cancelled = true;
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    playerRef.current?.pause();
    contextRef.current?.close();
  };
  ```
  `cancelled = true` only gates a later state update; `contextRef.current?.close()` closes the Web Audio `AudioContext`, which has no relationship to an in-flight `fetch()`. So even when this cleanup runs while a `loadAudioBuffer` call is in-flight, it cannot itself produce a fetch-level `AbortError`.
- The only thing that reliably aborts an in-flight `fetch()` with exactly this message is the **browser** cancelling network requests on page navigation/reload — standard web-platform behavior, not application code.
- Next.js's own documentation (`node_modules/next/dist/docs/03-architecture/fast-refresh.md`, `.../reactStrictMode.md`) confirms two **development-only** mechanisms that can trigger exactly this:
  1. Fast Refresh "will fall back to doing a full reload" when editing a file that's imported by files outside the React tree — a full reload aborts in-flight fetches at the browser level.
  2. React Strict Mode (default `true` for this app's App Router since Next.js 13.5.1, not overridden in `next.config.ts`) double-invokes effects (mount -> cleanup -> mount) on initial mount, in development only — never in a production build.
- The historical occurrence on record (`docs/status/2026-09-20-current-app-state.md` section 7, and a captured dev-server log line: `[loadAudioBuffer] attempt 1/3 failed for .../audio/accompaniment: AbortError: The operation was aborted.`) is for our own `loadAudioBuffer` call, consistent with this classification.
- Live reproduction was attempted extensively against the real running app (real YouTube pipeline job, Playwright-driven, network throttled via CDP to widen the race window, file edits timed against the in-flight fetch). A full `page.reload()` during a throttled in-flight fetch did not surface a logged error in this sandbox - most likely because the browser tears down the old document's JS context before its `.catch()` handler gets a chance to run `console.error`, which is itself consistent with "the browser cancels the request, not our code." A component-file edit intended to trigger Fast Refresh's in-place patch did not reliably land inside the fetch's (fast, loopback-network) window in this sandbox, whose dev server showed independent signs of a slow/degraded file watcher (`⚠ Slow filesystem detected` in its own log). Did not get a console-visible repro in this specific environment, but the causal mechanism (browser-level request cancellation from reload/HMR fallback, not app code) is independently confirmed by direct code reading, is standard, well-documented web-platform/framework behavior, and matches the one real historical occurrence on record.

**Classification: dev-only.** No `AbortController` exists anywhere in the app; `Player.tsx`'s cleanup cannot itself abort a fetch; the only mechanisms that can produce this exact error are browser-level request cancellation on reload/navigation, and Next.js Fast Refresh's documented full-reload fallback plus React Strict Mode's documented dev-only double-invoke — none of which exist in a production build. This is not a production-relevant request-lifecycle defect.

**Remaining acceptance criterion:** "no blanket catch suppresses real errors." Reading `Player.tsx`'s catch block:
```ts
} catch (error) {
  if (!cancelled) {
    console.error(`[Player] failed to load audio for job ${jobId}:`, error);
    setStatus("error");
  }
}
```
This already discriminates correctly: a real failure (not cancelled) is logged and surfaced via `status: "error"` (covered by existing tests `"should show an error message when audio fails to load"` and `"should log the underlying error and job id when audio fails to load"` in `Player.test.tsx`). A failure that occurs **after** cancellation (unmount, or effect cleanup) is silently dropped - correct, since the component is being torn down and a fresh load (or nothing) takes over. What's *not* currently tested is that this suppression is properly scoped to the cancelled case, i.e. it doesn't accidentally swallow something it shouldn't. This plan adds that missing coverage, completing the picture (surfaces-when-not-cancelled is already tested; suppresses-only-when-cancelled is not).

No production code change is needed: the existing behavior is already correct. This plan is test-only.

**Tech Stack:** TypeScript, Jest, React Testing Library (existing frontend stack).

**Spec:** GitHub issue #37 (V1-004), part of EPIC 1 (#28).

## Global Constraints

- No functional/behavioral code changes - the investigation concluded the existing suppression logic is already correct; only test coverage is missing.
- Do not introduce `AbortController` machinery speculatively: there is no current production scenario (no job-switching UI exists yet) where `Player`'s effect re-runs while a load is in-flight outside of dev-only StrictMode/Fast-Refresh double-invocation, so adding real cancellation plumbing now would be scope creep beyond this issue's acceptance criteria.
- Keep the change scoped to `Player.test.tsx` only.

---

### Task 1: Regression test proving cancelled-load failures are suppressed without swallowing real ones

**Files:**
- Modify: `frontend/components/__tests__/Player.test.tsx`

**Interfaces:**
- Consumes: existing `Player` component (unchanged), existing `loadAudioBuffer` mock pattern already used by `"should ignore an in-flight audio load that resolves after unmount"` (resolve-path) and `"should show an error message when audio fails to load"` (surfaces-path).

- [ ] **Step 1: Write the test**

Add to `frontend/components/__tests__/Player.test.tsx`, right after `"should ignore an in-flight audio load that resolves after unmount"`:

```tsx
  it("should not surface an error when an in-flight audio load rejects after unmount", async () => {
    const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    let rejectLoad!: (reason: unknown) => void;
    (loadAudioBuffer as jest.Mock).mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectLoad = reject;
      }),
    );

    const { unmount } = render(
      <Player
        apiBaseUrl="http://localhost:8000"
        jobId="job-1"
        events={[]}
        tempoBpm={120}
        createAudioContext={fakeContextFactory}
      />,
    );

    unmount();
    await act(async () => {
      // Shaped like the AbortError a dev-only Fast Refresh/Strict Mode
      // remount can produce - see docs/superpowers/plans/2026-09-20-abort-error-investigation.md.
      rejectLoad(new DOMException("The operation was aborted.", "AbortError"));
    });

    expect(consoleErrorSpy).not.toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
  });
```

This is a pure regression/characterization test for already-correct behavior, so there is no red step in the usual TDD sense - run it once to confirm it passes against the current, unmodified `Player.tsx`, which is itself the proof that the suppression is correctly scoped.

- [ ] **Step 2: Run the test**

Run: `cd frontend && pnpm test -- Player.test.tsx -t "should not surface an error when an in-flight audio load rejects after unmount"`
Expected: PASS immediately (no code change needed) - confirms the existing `if (!cancelled)` guard in `Player.tsx` already suppresses only the cancelled case.

- [ ] **Step 3: Run the full frontend suite, lint, and typecheck**

Run: `cd frontend && pnpm test`
Run: `cd frontend && pnpm lint`
Run: `cd frontend && npx tsc --noEmit`
Expected: all clean, no regressions.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/__tests__/Player.test.tsx
git commit -m "test: prove Player's error suppression is scoped to cancelled loads only"
```

---

## Self-Review Notes

- **Spec coverage:** "Root cause/classification is documented" -> this plan's investigation section, carried into the PR description with file/doc references. "production-relevant defect is fixed with regression coverage OR dev-only behavior is explicitly documented" -> classified dev-only with concrete supporting evidence (grep, code reading, official docs, live-repro attempt notes); no defect exists to fix. "no blanket catch suppresses real errors" -> verified by reading the existing catch block, and newly regression-tested (Task 1) alongside the pre-existing tests that already prove real errors surface.
- **Honesty check:** live reproduction was attempted but did not produce a console-visible repro in this sandbox; this is stated plainly rather than overclaiming a full end-to-end repro. The classification instead rests on direct code reading (no AbortController anywhere, cleanup never aborts a fetch) plus authoritative framework documentation, which is sufficient to explain the one confirmed historical occurrence.
