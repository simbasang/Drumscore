# Drumscore v1.0 Architecture

## Domain pipeline
Source -> normalized audio -> stem assets -> raw drum candidates -> timing analysis -> editable score -> engraving -> practice playback.

Each transition uses an application-owned contract.

## Timing model
The MVP scalar BPM/t=0 grid is replaced by a timing map.

Core concepts:
- TempoPoint: source time + BPM
- BeatPoint: source time + measure + beat + downbeat flag + optional confidence
- DrumEvent: immutable sourceTime + instrument + optional confidence/velocity + derived musicalPosition
- SongAnalysis: duration + tempoMap + beats + events

sourceTime survives every transformation. TempoMap describes musical timing relative to source audio; it is not the playback clock.

## Quantization
Quantization maps source timestamps to musical positions using detected beat/downbeat anchors. It accounts for phase/downbeat offset and varying beat durations, preserves sourceTime, records enough information to diagnose mapping, and avoids silently forcing uncertain events into implausible positions.

## Editable score
The application-owned score supports simultaneous hits, note/rest durations, grouping/ties where required, measures, add/delete/move/change-instrument operations, links to source events, and confidence/provenance metadata. Editor and renderer never operate directly on DrumScript/VexFlow structures.

## Engraving
VexFlow may remain the renderer but stays inside the engraving layer. Required style: five-line percussion staff, explicit upward stems, conventional positions, simultaneous grouping, readable beams/rests, explicit open/closed hi-hat and dynamic line breaking. Rendered elements retain score-event IDs for click-to-seek/editing. `DrumScore` takes an already-built `Score` as a prop (via `onSeek`-wired click handlers on each rendered note) rather than constructing one itself - score construction/editing state lives one level up (`useScoreEditor`, Epic 5), keeping the renderer a pure function of whatever `Score` it's handed. The instrument-to-staff-position/notehead mapping (including the closed/open hi-hat convention) is documented in `docs/notation-instrument-mapping.md`.

## Playback
One Web Audio transport owns source time, play/pause, seek, loop range, playback rate and synchronized stem start/stop. The playhead asks timing/score mapping where source time belongs; it never accumulates BPM ticks. `PracticeTransport` composes `SyncedPlayer` to add loop-range restart, playback-rate passthrough, metronome click scheduling and count-in on top of that authoritative clock, without changing `SyncedPlayer` itself.

## Transcription
DrumTranscriber remains the boundary. Candidate engines return normalized events and real confidence only when defensible. Evaluation uses labelled fixtures and per-class metrics. Raw outputs remain available in diagnostics so classification errors can be separated from timing/engraving errors.

## Jobs and persistence
Projects, jobs, artifacts, analyses, score versions and the stage cache are persisted in Postgres behind the `Store` protocol (`backend/app/persistence`). The API only enqueues. Separate `python -m app.worker` processes claim jobs with `FOR UPDATE SKIP LOCKED` leases, run each pipeline stage, and commit its output (written atomically to `ArtifactStorage`) before starting the next, so any crash resumes at the first stage without output. Retries are idempotent; stage outputs are reused across projects of the same source via a `PIPELINE_VERSION`-keyed cache. A pruner applies retention rules. Details: `docs/PERSISTENCE.md`.

Storage distinguishes source audio, stems, raw transcription diagnostics, analysis/score data and user edits.

## Observability
Every job has a correlation ID across API/worker/processing logs. Structured events record stage start/end/duration/failure. Timing diagnostics can compare raw source timestamp, nearest beat/downbeat, quantized musical position and rendered event. Implemented in V1-033; see docs/OPERATIONS.md for the log format, event catalogue, limits and secret handling.

## Deployment
One backend image runs the API, the workers and the one-shot migration step; a separate frontend image serves Next.js with the API URL as runtime configuration. Postgres and the artifact storage are the only persistent state (two named volumes). `/api/health` is liveness, `/api/ready` and `python -m app.readiness` are readiness. Implemented in V1-034; see docs/DEPLOYMENT.md.

## Testing
Unit: timing math, quantization, score transformations, engraving decisions, transport calculations.
Integration: adapters, API/job lifecycle, persistence, audio assets.
Golden/reference: known event sequences -> score model; labelled clips -> transcription metrics; score fixtures -> engraving properties.
E2E: submit -> process -> render -> play -> seek -> loop -> edit -> save -> reload. Automated at the API level in `backend/tests/test_release_e2e.py`; the browser half is `docs/RELEASE_CHECKLIST.md`, with v1.0 results in `docs/RELEASE_REPORT_V1.md`.

## Migration
Do not rewrite the MVP at once. Introduce new contracts beside old ones, migrate one boundary at a time, and remove legacy scalar-BPM/grid code only after tests prove the new path owns all consumers.
