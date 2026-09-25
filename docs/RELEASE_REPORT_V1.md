# v1.0 release report

Outcome of the V1-035 release gate (`docs/RELEASE_CHECKLIST.md`), run
2026-09-25 on branch `v1-035_release-gate`.

**Gate status: BLOCKED** on #113 (tempo octave error) and #114 (kick
detection). Everything else passed or was fixed on the branch. Re-run the
checklist once both are merged.

## Environment

- Clean deployment from `docs/DEPLOYMENT.md`: `down -v`, `build`, `up -d`,
  host ports 18000/13000, `WORKER_CONCURRENCY=1`, CPU-only torch.
- Host: Windows 11 + Docker Desktop, 15.6 GiB available to Docker.
- Songs: CCR — Have You Ever Seen the Rain (`bO28lB1uwp4`, 2:45, with a
  reference MIDI from the product owner); Rick Astley — Never Gonna Give You
  Up (`dQw4w9WgXcQ`, 3:33); an unavailable ID (`aaaaaaaaaaa`).
- Browser pass driven with Playwright (Chromium). Audible checks (does it
  *sound* in sync, do clicks land on the beat) cannot be judged by automation
  and remain for the product owner's sign-off.

## 1. Automated gate

| Check | Result |
|---|---|
| Backend `uv run pytest` | see PR (all pass) |
| Frontend Jest, lint, `tsc --noEmit` | see PR (all pass) |
| `tests/test_release_e2e.py` (Postgres): happy path with restart and reload, failure → retry, worker crash resume, duplicate cache reuse, delete + prune | 4/4 pass; each verified to fail when the stage cache or the pruner's delete is disabled |

## 2. Browser pass

| Step | Result | Evidence |
|---|---|---|
| Clean deploy, health/readiness | Pass | All services healthy, migrate exit 0, `/api/ready` and worker readiness OK |
| Submit → progress → completed | Pass | Stages shown in order; 156 s end to end |
| Notation engraving rules | Pass | Five-line staff, stems up, x noteheads, mixed durations, adaptive rows |
| Notation readability | **Fail → #113** | Tempo detected at 229.7 BPM (reference 115): notation in double time, unbeamed 16ths |
| Play / playhead | Pass | Transport advances at real time; playhead monotonic within rows, clean row cuts |
| Slider seek | Pass | Jumps to 60 s, playhead follows |
| Click-to-seek on a note | Pass | Playhead lands 10 px from the clicked note |
| A/B loop | Pass | 40.0–43.1 s wrapped 4× consistently |
| Playback speed | Pass | Measured rate 0.51 / 0.746 / 1.259 / 1.503 / 1.008 for 0.5–1.5× |
| Count-in | Pass (mechanics) | 4 clicks (~1.0 s), then playback from the paused position; Play disabled meanwhile. Clicks are 8th notes because of #113 |
| Metronome | Pass (mechanics) | No errors or stalls; clicks follow the beat map, which is 2× (#113) |
| Edit: delete / change / move / add | Pass | Hit list and render update per edit, "Unsaved changes" shown |
| Undo ×4 / redo ×4, save (Ctrl+S) | Pass | Back to original (clean), forward to final, "All changes saved" |
| Reload | Pass | Saved v1 score loads, no reprocessing |
| `restart api worker`, `down` + `up` | Pass | Project, edits and score v1 survive |
| Unavailable video → retry | Pass | Readable error alert; retry requeues; fails cleanly again |
| Worker restart mid-separation | Pass | Stage finished, job released (`abandoned`, attempt refunded), resumed at `transcribe`, no second download |
| API outage while polling | Pass | "Lost connection" → gives up after 3 polls with reload alert; recovers on reload |
| Duplicate → Open existing / Process anyway | Pass | Prompt offered; reprocess from stage cache |
| Delete → prune | **Fail → fixed on branch** | 72 MB freed, but DrumScript's side output (~0.5 MB/job) survived; see Defects |

## 3. Performance and resource baseline

| Measure | CCR (2:45) | Rick Astley (3:33) |
|---|---|---|
| extract | 3.0 s | 4.2 s |
| separate (Demucs, CPU) | 101.1 s | 120.9 s |
| transcribe (DrumScript) | 38.2 s | 43.3 s |
| map_tempo | 13.9 s | 13.8 s |
| **Total** | **156 s (0.95× song length)** | **182 s** (split by a worker restart) |
| Artifact disk, completed | 84 MB → 56 MB after source-audio prune | 108 MB before prune |
| Duplicate reprocess | 5.5 s (separate/transcribe cached, map_tempo rerun) | — |

- Peak worker memory 1.6 GiB (388 samples at ~2 s), API 77 MiB; no OOM, no
  container restarts.
- Score for 716 hits / ~90 measures: analysis and score responses ~150 ms;
  SVG in the DOM ~1.7 s after navigation; each engraving pass 260–290 ms
  (a long task).
- Long tasks during playback, seek, loop, speed and count-in: **none**.

**Invariants:** no OOM ✔ · storage reclaimed after delete + prune ✔ (after
the fix below) · duplicate served from stage cache ✔ · no main-thread stall
during playback ✔.

## Defects

1. **DrumScript side output never pruned (fixed on this branch).**
   `drumscript_runner/run_transcription.py` wrote DrumScript's
   `drumscript_output/` (JSON, MIDI, PDF; ~0.5 MB per job) next to the drums
   stem, i.e. inside artifact storage with no `artifacts` row, so the pruner
   could never remove it, even after the project was purged. Fix: the
   transcriber passes a directory inside its own temporary scratch
   directory; regression tests in `test_drumscript_transcriber.py` and
   `test_drumscript_runner_script.py`; verified on the rebuilt stack (a new
   job stores only its four tracked artifacts). Existing deployments need a
   one-off cleanup (`docs/DEPLOYMENT.md` §6).
2. **Tempo octave error (#113, release-blocking).** 229.7 vs 115 BPM on CCR,
   57.4 vs ~113 on Rick Astley. Notation, metronome and count-in follow the
   wrong pulse.
3. **Kick detection (#114, release-blocking).** Compared with the reference
   MIDI (tempo-tolerant alignment, 50 ms, greedy per-instrument matching as in
   `app/benchmark.py`): kick 16 detected vs 263 (F1 0.01), snare F1 ≤ 0.31,
   hi-hat (open+closed) F1 ~0.55, instrument-agnostic onsets F1 0.61. Raw
   DrumScript output already has only 17 kicks. One fan-made MIDI is not
   labelled ground truth, but the kick recall ceiling (~6%) is count-based.

## Known limitations (non-blocking)

From the `TECHNICAL_DEBT.md` index and this pass:

- No authentication, no TLS/reverse proxy, CPU-only image (no GPU).
- Transcription quality beyond #114: classifier accuracy is measured only on
  a synthetic corpus; no real confidence values from DrumScript.
- Notation: no dotted/tied durations; beams don't cross intra-beat rests.
- Editing re-engraves the whole score synchronously (260–290 ms per edit): the
  playhead stalls briefly when editing during playback (new debt entry).
- `GET /score` returns 404 before the first save, which shows as a console
  error (new debt entry).
- A graceful worker stop waits for the running stage (up to the 10-minute
  `stop_grace_period`) by design.
- Purged projects leave empty directories in storage (new debt entry).
- Pruner/lease edge cases recorded in `TECHNICAL_DEBT.md` (pruner races,
  lost-lease overwrite, advisory admission limits).

## Definition of Done

| DoD clause (`PROJECT.md`) | Status | Evidence |
|---|---|---|
| Submit a song | ✔ | §2 submit |
| Reliable processing progress | ✔ | §2 progress, API outage, failure → retry |
| Readable notation aligned to the recording | **✘ #113, #114** | Engraving rules pass; tempo 2× and missing kicks make the result unreadable for this song |
| Synchronized stems | ✔ (automated + transport timing; audible check pending sign-off) | §2 play/seek/loop/speed |
| Reduce/mute drums | ✔ (automated; audible check pending sign-off) | REGRESSION_CHECKLIST §6 |
| Seek by audio or score | ✔ | §2 slider and click-to-seek |
| Loop sections | ✔ | §2 A/B loop |
| Change playback speed | ✔ | §2 measured rates |
| Correct events | ✔ | §2 editor, undo/redo |
| Save and reload without reprocessing | ✔ | §2 reload, restart, down/up; `test_release_e2e.py` |
| No known data-loss defects | ✔ | Persistence steps; crash-resume test |
| No runaway-resource defects | ✔ after fix | Defect 1 fixed; memory bounded; storage reclaimed |
| No core playback-sync defects | ✔ | No stalls, monotonic playhead, loop/rate/seek consistent |

**Sign-off:** pending. The product owner signs off after #113 and #114 are
merged and this checklist is re-run, including the audible checks.
