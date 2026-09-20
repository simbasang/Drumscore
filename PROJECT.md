# Drumscore v1.0 Project Plan

## Product goal
Turn the working MVP into a stable, production-quality drum-practice product. A user should be able to submit a supported song, receive accurate and readable drum notation, correct mistakes, and practise against synchronized audio with the original drums reduced or muted.

## Current baseline
The MVP already provides Next.js/React/TypeScript, FastAPI/Python, yt-dlp + ffmpeg extraction, Demucs stem separation, DrumScript transcription, librosa tempo estimation, VexFlow notation, Web Audio playback, independent drum volume, retry/cleanup/concurrency limits and automated tests.

The major v1.0 limitations are architectural: one scalar BPM per song; a quantization grid anchored at t=0 without downbeat/phase alignment; rendered timing reconstructed from the grid rather than source timestamps; every hit represented as a sixteenth note; limited DrumScript classification quality and no useful confidence values; unresolved playhead jumping/AbortError; and MVP-only in-process jobs/local artifact storage.

## Non-negotiable engineering rules
1. Source audio time is authoritative. Every DrumEvent retains its original absolute source timestamp.
2. Diagnose before fixing: reproduce, instrument, prove root cause, add regression coverage, fix, verify.
3. Do not patch symptoms such as smoothing a playhead whose underlying timing model is wrong.
4. Keep acquisition, separation, transcription, timing, score modelling, engraving, playback, persistence and UI separated behind application-owned contracts.
5. Preserve the notation style: five-line percussion staff, all stems upward including kick/snare, simultaneous hits grouped/aligned, readable rhythmic durations/beams and clear open/closed hi-hat.

## Target timing architecture
Keep three concepts separate:
- sourceTime: original timestamp in audio
- musicalPosition: measure/beat/subdivision derived from beat/downbeat/tempo analysis
- renderedPosition: screen coordinates created by engraving

The player uses sourceTime. The score model links sourceTime to musicalPosition. The renderer maps musicalPosition to renderedPosition.

## Delivery plan

### Epic 1 — Instrumentation & Stabilization
Make failures measurable before changing core algorithms. Add diagnostic fixtures and event-pipeline inspection, reproduce/fix playhead jumping, investigate AbortError, harden polling/network behavior, and establish a regression baseline.

Exit gate: runtime defects are reproducible or explicitly classified, and raw transcription -> timing -> score data can be inspected for the same song.

### Epic 2 — Timing Engine 2.0
Replace scalar BPM/t=0 grid with TempoMap, beat/downbeat detection, phase alignment, tempo ambiguity handling and timestamp-aware quantization. Frontend score following must use mapped source timestamps.

Exit gate: complete songs stay aligned despite silence/count-ins, human timing and moderate tempo variation.

### Epic 3 — Transcription Engine 2.0
Build a labelled benchmark, measure per-instrument accuracy, compare candidate engines, add real confidence support, choose/tune the production strategy and add defensible post-processing.

Exit gate: selected transcription strategy has documented measured quality and materially improves on the MVP baseline.

### Epic 4 — Notation Engine 2.0
Replace the dense sixteenth-note event grid with musically readable notation: note-duration consolidation, correct beams/grouping, improved hi-hat notation, dynamic layout, timestamp-linked rendered events and visual/reference regression tests.

Exit gate: representative grooves render as conventional readable drum notation.

### Epic 5 — Practice Player & Correction Editor
Add A/B loop, playback speed, count-in/metronome, click-to-seek, manual correction, confidence-assisted review and undo/redo.

Exit gate: a user can generate, correct and practise a song without leaving Drumscore.

### Epic 6 — Productionization & v1.0
Add persistent projects/jobs, durable queue/workers, durable artifact storage, caching/idempotency, observability, resource/security limits, deployment/containerization and E2E/release validation.

Exit gate: jobs recover across restarts, projects persist, operations are observable and deployment/release is documented.

## Quality gates
Regression coverage must include timestamp preservation, beat/downbeat/tempo-map mapping, quantization, simultaneous grouping, forced upward stems, note/rest duration construction, playhead mapping/seeking, two-stem synchronization, mixer behavior, editor transformations and job lifecycle/recovery.

Audio/ML work requires representative real-song fixtures in addition to unit tests.

## v1.0 Definition of Done
A user can submit a song; see reliable processing progress; receive readable notation aligned to the recording; hear synchronized stems; reduce/mute drums; seek by audio or score; loop sections; change playback speed; correct events; save the corrected project; reload it later without reprocessing; and use the application without known data-loss, runaway-resource or core playback-sync defects.

## Post-v1.0 unless evidence pulls them forward
Social/collaboration, public sharing marketplace, native mobile apps, live e-drum scoring, Guitar Hero-style judgement, automatic difficulty generation, advanced export and custom model-training infrastructure.

## Issue execution
GitHub issues are the executable plan. Work in dependency order and do not combine unrelated issues merely because they touch the same files. CLAUDE.md defines the required AI-assisted working method.
