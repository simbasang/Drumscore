# v1.0 release report

Outcome of the V1-035 release gate (`docs/RELEASE_CHECKLIST.md`).

**Gate status: PASSED (pass 3), pending the product owner's sign-off.** #118
(V1-038) is merged and every checklist step passes on a clean deployment. No
new defects. Remaining: the audible checks and DoD sign-off (see the end).

## History

| Pass | Date | Branch | Outcome |
|---|---|---|---|
| 1 | 2026-09-25 | `v1-035_release-gate` | Blocked on #113 (tempo octave error, 229.7 vs 115 BPM) and #114 (17 vs 263 kicks). Fixed on the branch: DrumScript side output never pruned. Full report in git history (PR #115). |
| 2 | 2026-09-27 | `v1-035_release-gate-rerun` | #113 and #114 confirmed fixed. New: count-in lockup (fixed on the branch) and quantized DrumScript times (#118, release-blocking). Details under Pass 2 below. |
| 3 | 2026-10-01 | `v1-035_release-gate-pass3` | #118 confirmed fixed; count-in fix confirmed. No new defects. This report. |

## Pass 3 (2026-10-01)

### Environment

- `main` at `eee504d` (#120, V1-038 merged). No code changes on this branch.
  Frontend code is unchanged since pass 2; the backend change is V1-038 only
  (`PIPELINE_VERSION` 4, verified inside the worker image).
- Clean deployment per `docs/DEPLOYMENT.md`: pass-2 stack removed with
  `down -v`, images rebuilt, compose project `drumscore-v1035p3` with fresh
  volumes, host ports 18000/13000, `WORKER_CONCURRENCY=1`, CPU-only torch.
- Songs: CCR (`bO28lB1uwp4`, 2:45, reference MIDI), Rick Astley
  (`dQw4w9WgXcQ`, 3:33), and for the memory check Toto — Africa
  (`FTQbiNvZqaY`, 4:55) and Queen — Bohemian Rhapsody (`fJ9rUzIMcZQ`, 5:59).
  Unavailable IDs `aaaaaaaaaaa`, `aaaaaaaaaab`.
- Browser pass driven with Playwright (Chromium), instrumented as in pass 2:
  `AudioBufferSourceNode.start` / `OscillatorNode.start` (with
  `context.currentTime`) map every stem start, metronome and count-in click
  to source time; the playhead is sampled per animation frame.

### 1. Automated gate

| Check | Result |
|---|---|
| Clean deploy, health/readiness | Pass: all services healthy, migrate exit 0, `/api/ready` OK (database at head, storage writable) |
| Backend `uv run pytest` (incl. `tests/test_release_e2e.py` on Postgres) | 570 passed |
| Frontend Jest | 308 passed |
| `pnpm lint`, `npx tsc --noEmit` | Clean (lint's only warning is in the git-ignored `coverage/` report) |

### 2. Browser pass

| Step | Result | Evidence |
|---|---|---|
| Submit → progress → completed | Pass | "Downloading audio..." → completed; CCR 160.4 s end to end |
| Source onset times (#118 re-check) | Pass | Non-kick `source_time`s are detected onsets, not a grid (e.g. snare 1.1204 s, quantized 1.12 s). Events match the V1-038 evaluation run: snare 144/145, closed hi-hat 421/430, crash 48/50 identical (median Δ 0 ms); kick 264/290 (Demucs run-to-run variation) |
| Tempo / beats | Pass | CCR 116.5 BPM, 297 beats; Rick Astley 113.2 BPM, 400 beats (as in pass 2) |
| Notation engraving | Pass | 4/4 five-line staff, stems up, beamed hi-hats, backbeat snare, mixed durations and rests, adaptive rows; 570 clickable notes |
| Play / playhead | Pass | Rate 1.000 over 10 s; playhead monotonic within rows; no long tasks |
| Slider seek | Pass | 20 → 60 s immediately; rate 1.000 after the seek |
| Click-to-seek on a note | Pass | Playhead lands 6 px from the clicked note |
| A/B loop | Pass | 40.25–43.3 s: stems restart at 40.25 s every 3.06 s from the first pass; `Clear loop` resumes |
| Speed | Pass | Measured 0.498 / 0.748 / 0.999 for 0.5× / 0.75× / 1× |
| Metronome | Pass | 20 clicks at 1× (across a seek) and 8 at 0.75× all land on a beat-map beat (0 ms error) |
| Count-in | Pass | 4 clicks 0.52 s apart (local beat period 0.52 s), stems start one beat after the last click, Play/Count-in disabled meanwhile |
| Count-in from the end (pass-2 Defect 1) | Pass | Controls re-enabled after the count-in; no lockup |
| Edit: delete / change / move / add | Pass | Hit list and render update per edit; "Unsaved changes" |
| Undo ×4 / redo ×4, save (Ctrl+S) | Pass | Undo returns exactly to the original (Undo disabled), redo matches the forward state, "All changes saved", score v1 |
| Reload | Pass | Saved edits load (985 hits, changed hit shows `crash`), no new job |
| `restart api worker`, `down` + `up` | Pass | Score v1 with edits survives both; latest job unchanged (no reprocessing) |
| Unavailable video → retry | Pass | "Failed to download audio: … This video is unavailable"; retry requeues ("Queued…") and fails cleanly again |
| Worker restart mid-separation | Pass | `separate` finished, job `abandoned` and reclaimed, resumed at `transcribe`, no second extract |
| API outage while polling | Pass | "Lost connection, retrying..." → "Lost connection to the server… reload the page"; recovers after restart |
| Duplicate → Open existing / Process anyway | Pass | Both offered; `separate`/`transcribe` `cached`, only `map_tempo` ran (5.4 s) |
| Delete → prune | Pass | Rick Astley 109 MB → 8 KB (empty directory) after the prune, once no live project referenced its artifacts |

Resubmitting a deleted song before the prune reuses its cached stages (all
`cached`, job done in 7 s); the prune then keeps the storage keys the new
project references (its audio and analysis stay served) and purges only the
deleted project's row and unreferenced keys. That is the intended content
cache, and no artifact was lost.

### 3. Performance and resource baseline

| Measure | CCR (2:45) | Rick Astley (3:33) | Toto (4:55) | Queen (5:59) |
|---|---|---|---|---|
| extract | 3.2 s | 5.3 s | 3.3 s | 3.3 s |
| separate (Demucs, CPU) | 101.9 s | 143.9 s | 149.7 s | 197.9 s |
| transcribe | 46.0 s | 33.2 s | 52.8 s | 46.1 s |
| map_tempo | 8.2 s | 9.6 s | 10.5 s | 11.8 s |
| **Total** | **160.4 s (0.97× song length)** | 191.9 s | 216.3 s | 259.0 s |
| Artifact disk | 84 MB → 56 MB after source-audio prune | 109 MB → 73 MB | — | — |

- Worker memory, sampled every 2–12 s: separation peaks at 1.6–1.8 GiB for
  the first job in a worker process and 2.2–2.8 GiB for a second one right
  after it (Rick Astley 2.8 GiB after CCR; Queen 2.56 GiB after Toto). It
  falls back to ~0.6 GiB when the queue is empty, so it is bounded and
  released per job, not accumulating. Pass 2 reported 1.6 GiB because its
  second job was split by the worker restart. Size hosts for ~3 GiB per
  worker slot. API ≤ 90 MiB. No OOM kills, no unplanned restarts.
- Score (985 hits): analysis 43 ms, saved score 15 ms; clickable notes within
  1.46 s of navigation; engraving is two long tasks of 162–184 ms at load and
  one of 159 ms per edit (pass 2: 160–190 ms).
- Long tasks during playback, seek, loop, speed, metronome and count-in:
  **none**.

**Invariants:** no OOM ✔ · storage reclaimed after delete + prune ✔ ·
duplicate served from the stage cache ✔ · no main-thread stall during
playback ✔.

### Measurement note: reference-MIDI alignment

The throwaway `midi_compare.py` (V1-037) aligns the reference MIDI to the
recording by pooled, instrument-agnostic onset matches. On CCR's steady
eighth-note hi-hats a whole-beat shift scores almost as well, so the fit can
lock onto the wrong beat: on this pass's output it picked an offset 1.55 s
(3 beats) away from the V1-038 run's and reported kick 0.25 / snare 0.05 for
events identical to that run's. An instrument-aware fit picks yet another
offset. Per-instrument F1 against this MIDI is therefore not reliable at beat
precision, and pass 3 establishes "no regression" by the direct
event-by-event comparison above. Instrument-agnostic onset F1 (0.92) is
unaffected.

## Pass 2 (2026-09-27)

### Environment

- `main` at `e07f1db` (V1-037 merged) plus this branch. Clean deployment per
  `docs/DEPLOYMENT.md`: compose project `drumscore-v1035r` with fresh volumes,
  host ports 18000/13000, `WORKER_CONCURRENCY=1`, CPU-only torch.
- Host: Windows 11 + Docker Desktop, 15.6 GiB available to Docker.
- Songs: CCR — Have You Ever Seen the Rain (`bO28lB1uwp4`, 2:45, with the
  product owner's reference MIDI); Rick Astley — Never Gonna Give You Up
  (`dQw4w9WgXcQ`, 3:33); unavailable IDs `aaaaaaaaaaa`, `aaaaaaaaaab`.
- Browser pass driven with Playwright (Chromium) against the stack. Timing
  was checked by instrumenting `AudioBufferSourceNode.start` and
  `OscillatorNode.start` and mapping every metronome and count-in click to
  source time. Whether it *sounds* in sync is left to the product owner's
  sign-off.

### 1. Automated gate

| Check | Result |
|---|---|
| Clean deploy, health/readiness | Pass: all services healthy, migrate exit 0, `/api/ready` and worker readiness OK, empty library, no console errors |
| Backend `uv run pytest` (incl. `tests/test_release_e2e.py` on Postgres) | 568 passed |
| Frontend Jest | 308 passed (305 + 3 regression tests for the count-in fix) |
| `pnpm lint`, `npx tsc --noEmit` | Clean (lint's only warning is in the locally generated, git-ignored `coverage/` report) |

### 2. Browser pass

| Step | Result | Evidence |
|---|---|---|
| Submit → progress → completed | Pass | Queued → Downloading → Separating → … → completed; CCR 150.6 s end to end |
| Tempo (#113 re-check) | Pass | CCR 116.5 BPM (reference 115), 297 beats; Rick Astley 113.2 BPM (was 57.4) |
| Kicks (#114 re-check) | Pass | CCR 286 kicks (reference 263), kick F1 0.63 (was 0.01) |
| Notation engraving | Pass | 4/4 five-line staff, stems up, beamed eighth hi-hats, kick/snare backbeat, mixed durations and rests, adaptive rows |
| Play / playhead | Pass | Rate 0.998–1.000; playhead monotonic within rows across 3 row changes; no long tasks |
| Slider seek | Pass | 21.6 → 60 s immediately; playhead follows |
| Click-to-seek on a note | Pass | Playhead lands 6 px from the clicked note |
| A/B loop | Pass | 40.25–43.3 s wrapped 5× at a steady 3.05 s period; `Clear loop` resumes |
| Speed with loop active | Pass | Measured 0.500 / 0.747 / 1.002 for 0.5× / 0.75× / 1× |
| Metronome | Pass | Every click at 1×, at 0.75× and after two seeks lands on a beat-map beat (≤ 2.7 ms); clicks are quarter notes now |
| Count-in | Pass after fix | 4 clicks 0.50 s apart (local beat period 0.50–0.52 s), stems start one beat after the last click, Play disabled meanwhile. **Defect 1** found and fixed |
| Edit: delete / change / move / add | Pass | Hit list and render update per edit; "Unsaved changes" |
| Undo ×4 / redo ×4, save (Ctrl+S) | Pass | Back to the original (clean), each redo matches its forward step, "All changes saved" |
| Play after edits | Pass | Rate 0.997, playhead monotonic |
| Reload | Pass | Saved score v1 with all edits loads; no new job |
| `restart api worker`, `down` + `up` | Pass | Score v1 with edits survives both; no reprocessing |
| Unavailable video → retry | Pass | "Failed to download audio: … This video is unavailable"; retry requeues and fails cleanly again |
| Worker restart mid-separation | Pass | `separate` finished, job released (`abandoned`, attempt refunded), resumed at `transcribe`, no second extract |
| API outage while polling | Pass | "Lost connection, retrying..." → `poll 3/3 failed` → reload alert; page recovers on reload |
| Duplicate → Open existing / Process anyway | Pass | Both offered; `separate`/`transcribe` `cached`, only `map_tempo` ran (6.9 s) |
| Delete → prune | Pass | Rick Astley 73 MB → empty directory after the next prune ("purged 1 projects"); no untracked DrumScript output left |
| Transcription timing vs reference | **Fail → #118** | See Defect 2 |

### 3. Performance and resource baseline

| Measure | CCR (2:45) | Rick Astley (3:33) |
|---|---|---|
| extract | 3.4 s | 4.6 s |
| separate (Demucs, CPU) | 95.5 s | 114.2 s |
| transcribe (DrumScript + kick detector) | 43.0 s | 47.0 s |
| map_tempo (Beat This!) | 8.7 s | 9.2 s |
| **Total** | **150.6 s (0.91× song length)** | 175.0 s (split by the worker restart) |
| Artifact disk | 56 MB after source-audio prune | 73 MB before prune |
| Duplicate reprocess | 6.9 s | — |

- Peak worker memory 1.6 GiB (3,969 samples at ~2 s), API 95 MiB. No OOM and
  no unplanned container restarts.
- Score (984 hits): analysis and score responses ~40 ms; clickable notes in
  the DOM within 1.3 s of navigation; engraving is two long tasks of
  160–190 ms at load and per edit (was 260–290 ms in pass 1).
- Long tasks during playback, seek, loop, speed, metronome, count-in and 30 s
  of looped playback with the metronome on: **none**; the playhead never
  froze.

**Invariants:** no OOM ✔ · storage reclaimed after delete + prune ✔ ·
duplicate served from the stage cache ✔ · no main-thread stall during
playback ✔.

### Defects

1. **Count-in from the end of the track locks the transport (fixed on this
   branch).** With the position at the end (e.g. after the song finished),
   `Count-in` left Play/Pause and Count-in disabled until a reload; seeking
   didn't recover. `Player.tick()` only ended a count-in when it observed
   `transport.isPlaying`, but `play()` at `offset == duration` stops again
   in the same frame, so it never did. Fix: `PracticeTransport.isCountingIn`
   reports the pending count-in timer and the tick derives the UI state from
   it. Regression tests in `PracticeTransport.test.ts` and
   `Player.test.tsx`; verified in the rebuilt frontend (count-in from the end
   re-enables the controls; count-in mid-song unchanged).
2. **DrumScript event times are grid-quantized (#118, release-blocking).**
   DrumScript's `transcribe()` snaps every event to a 16th grid at its own
   single tempo and overwrites `time_sec` in place before returning it, so
   every non-kick event's source timestamp is a grid time (on CCR, 448 of 551
   intervals are exactly 0.2554 s). This breaks the timing model (source time
   is authoritative) and the DoD's "notation aligned to the recording".
   Same stem, against the reference MIDI:

   | | shipped (quantized) | DrumScript raw onsets |
   |---|---|---|
   | onsets, instrument-agnostic F1 | 0.69 | 0.91 |
   | hi-hat merged F1 | 0.65 | 0.88 |
   | snare F1 | 0.39 | 0.56 |
   | kick F1 (own detector) | 0.63 | 0.65 |

   The V1-037 CCR figures for snare/hi-hat (0.56/0.88) were measured on raw
   onsets, which is why they didn't match what ships. `TECHNICAL_DEBT.md` has
   the entry.

## Known limitations (non-blocking)

From the `TECHNICAL_DEBT.md` index and passes 2–3:

- No authentication, no TLS/reverse proxy, CPU-only image (no GPU).
- Transcription quality: onset timing is fixed (#118), but snare/hi-hat
  classification is weak on real audio (Rick Astley: 62 snares against ~200
  backbeats; CCR open hi-hat recall ~0.3), no open/closed
  or cymbal labels in the real-audio benchmark, DrumScript emits no toms, no
  real confidence values.
- Notation: meter fixed at 4/4; single global tempo and phase; no
  dotted/tied durations; beams don't cross intra-beat rests.
- No vertical auto-scroll: during playback the playhead moves below the
  viewport on a full song.
- Every edit re-engraves the whole score synchronously (159–184 ms).
- `GET /score` returns 404 before the first save (a console error), and the
  duplicate check's 409 also shows as one.
- A graceful worker stop waits for the running stage (up to the 10-minute
  `stop_grace_period`) by design.
- Purged projects leave empty directories in storage.
- Separation memory is 1.6–2.8 GiB per worker slot (higher for longer songs
  and for the second job in a process; released after each job).
- Pruner/lease edge cases recorded in `TECHNICAL_DEBT.md` (pruner races,
  lost-lease overwrite, advisory admission limits).

## Definition of Done

Section references are to Pass 3.

| DoD clause (`PROJECT.md`) | Status | Evidence |
|---|---|---|
| Submit a song | ✔ | §2 submit |
| Reliable processing progress | ✔ | §2 progress, API outage, failure → retry, worker restart |
| Readable notation aligned to the recording | ✔ (visual check pending sign-off) | Tempo and kicks fixed (#113, #114); source onset times fixed (#118): §2 onset re-check; engraving rules pass |
| Synchronized stems | ✔ (instrumented; audible check pending sign-off) | §2 play/seek/loop/speed; both stems start together at one offset |
| Reduce/mute drums | ✔ (automated; audible check pending sign-off) | REGRESSION_CHECKLIST §6 |
| Seek by audio or score | ✔ | §2 slider and click-to-seek |
| Loop sections | ✔ | §2 A/B loop |
| Change playback speed | ✔ | §2 measured rates |
| Correct events | ✔ | §2 editor, undo/redo |
| Save and reload without reprocessing | ✔ | §2 reload, restart, down/up; `test_release_e2e.py` |
| No known data-loss defects | ✔ | Persistence steps; crash-resume; cache reuse after delete keeps referenced artifacts |
| No runaway-resource defects | ✔ | §3 memory bounded and released per job; storage reclaimed |
| No core playback-sync defects | ✔ | No stalls; monotonic playhead; loop/rate/seek/metronome/count-in consistent |

**Sign-off:** pending the product owner's audible and visual checks on the
pass-3 stack (`drumscore-v1035p3`, http://localhost:13000, CCR project with
saved edits): stems in sync while playing, seeking, looping and at 0.75×;
drums volume reduces/mutes the drums; metronome and count-in sound on the
beat; notation reads as the song. When signed off, record it here and close
#86 and #33.
