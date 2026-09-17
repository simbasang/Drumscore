# Claude instructions — Drumscore

You are helping build **Drumscore**.

Before making architectural or implementation decisions, read `PROJECT.md` completely. It is the product specification and MVP plan.

## Goal

Build the MVP described in `PROJECT.md`: a web application where a user submits a YouTube URL, the application extracts and separates the audio, automatically transcribes the drums, renders readable drum notation, and provides a synchronized practice player where the original drum track can be reduced or muted.

## Working method

Work incrementally and do not attempt to build the entire application in one uncontrolled pass.

Follow the MVP tasks in `PROJECT.md` in order unless there is a concrete technical reason to change the order.

For each task:

1. Inspect the existing repository and understand what is already implemented.
2. State briefly what you intend to change.
3. Implement the smallest complete solution satisfying that task's acceptance criteria.
4. Add or update relevant tests.
5. Run available tests, linting and type checking.
6. Fix failures caused by your changes.
7. Keep changes scoped to the current task.
8. Update documentation when setup or architecture changes.

Do not silently replace major architectural choices. If a planned technology turns out to be unsuitable, explain the reason and propose the smallest appropriate alternative.

## Architecture principles

The most important rule is:

**The source audio timeline is the source of truth.**

Every detected drum hit must retain its original timestamp. Quantization and musical notation may add measure, beat and subdivision information, but must not destroy or replace the original timing information.

Keep these concerns separated:

- media/source acquisition
- audio processing
- stem separation
- drum transcription
- tempo/beat mapping
- application-owned score representation
- notation rendering
- audio playback
- UI

Use interfaces/adapters around experimental or replaceable dependencies such as YouTube extraction, Demucs and drum-transcription models.

Do not let frontend code depend directly on raw model output.

## Preferred stack

Unless the repository establishes a better equivalent:

Frontend:

- Next.js
- React
- TypeScript
- VexFlow
- Web Audio API

Backend:

- Python
- FastAPI
- ffmpeg
- yt-dlp for the initial source adapter
- Demucs for initial stem separation

For drum transcription, evaluate suitable maintained open-source implementations/models before writing custom ML code. Hide the selected implementation behind a transcription interface.

## Drum notation requirements

These are product requirements, not optional visual preferences.

Generated notation must use a standard percussion staff and appropriate vertical drum positions.

Most importantly:

**All note stems must point upward.**

This includes bass drum, snare, hi-hat, cymbals and toms.

When hits occur simultaneously, render them together/aligned at the same rhythmic position and use a shared/grouped upward stem where the renderer permits it.

Examples include:

- kick + hi-hat
- snare + hi-hat
- kick + snare + crash

Do not rely on VexFlow defaults if those defaults violate these rules. Configure or extend the rendering layer explicitly.

Open and closed hi-hat must also be visually distinguishable.

## Playback synchronization

Do not build a notation clock that independently accumulates elapsed time.

The audio playback clock determines current time. The notation/playhead reads that time and displays the corresponding score position.

`requestAnimationFrame` may be used for UI refresh, but not as the authoritative playback clock.

The design must remain capable of handling tempo changes and recordings that do not sit perfectly on a fixed BPM grid.

## Audio mixer

The MVP requires at least two synchronized playback stems:

- accompaniment
- drums

The player must expose independent drum volume from 0–100%.

At 0%, the user hears the accompaniment without the original drums. Changing drum volume must not change playback position or synchronization.

Prefer Web Audio API gain nodes or an equivalent sample/timeline-synchronized solution.

## Quality rules

Prefer readable, boring, maintainable code over clever abstractions.

Do not prematurely build infrastructure intended only for hypothetical scale.

Do not add authentication, databases, cloud infrastructure or other out-of-scope features unless they become technically necessary for the current MVP task.

Use strong types at module boundaries.

Validate API input and return useful errors.

Avoid giant components and giant processing modules.

Add tests around deterministic logic, particularly:

- transcription-model output mapping
- timestamp preservation
- beat/measure quantization
- simultaneous event grouping
- upward stem decisions
- player synchronization calculations
- drum mixer state

## Initial instruction

Start with **MVP-001 — Project foundation** from `PROJECT.md`.

First inspect the repository. Then propose the concrete file/folder structure and dependencies for MVP-001. After that, implement MVP-001 only.

Do not proceed automatically through every remaining MVP task in the same change. The project should remain reviewable task by task.
