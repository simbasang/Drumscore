# Drumscore MVP Project Plan

## 1. Project goal

Build a web application where a user can paste a YouTube URL, automatically generate a drum transcription, and then practise along with the song in a synchronized notation player.

The experience should be inspired by Songsterr, but focused specifically on drums, with an emphasis on:

- automatic drum transcription
- accurate timing
- clear drum notation
- smooth playback without notation/audio drifting out of sync
- the ability to reduce or mute the original drum track while practising

The MVP should prioritize a reliable end-to-end workflow over advanced editing or polish.

---

## 2. Core user flow

1. User opens the application.
2. User pastes a YouTube URL.
3. User clicks **Generate drum score**.
4. The application downloads/extracts the audio.
5. The drum stem is separated from the rest of the song.
6. The drum stem is analysed and converted into timestamped drum events.
7. Drum events are transformed into musical measures and drum notation.
8. The generated notation is displayed in a synchronized player.
9. The user presses play and sees a playhead follow the notation.
10. The user can reduce or mute the original drum stem and play along themselves.

---

## 3. MVP scope

### 3.1 YouTube input

The application must provide a simple input where the user can paste a YouTube URL.

Requirements:

- validate that the URL is supported
- submit the URL for processing
- display processing progress/status
- show useful errors when processing fails

Implementation detail should be isolated behind a media-source abstraction so YouTube handling can later be replaced or extended with local uploads or other providers.

---

### 3.2 Audio extraction

Extract an audio stream suitable for analysis and playback.

Suggested tooling:

- `yt-dlp`
- `ffmpeg`

The rest of the application should not depend directly on yt-dlp-specific data structures.

---

### 3.3 Stem separation

Separate at minimum:

- drums
- accompaniment / everything else

Suggested starting point:

- Demucs

The generated player must be able to play the accompaniment and drum stem simultaneously while controlling the drum stem independently.

---

### 3.4 Drum transcription

The drum-analysis pipeline should identify at least the following event types for the MVP:

- kick / bass drum
- snare
- closed hi-hat
- open hi-hat
- crash cymbal
- ride cymbal
- toms where reasonably detectable

Each detected event must retain its original timestamp.

Example internal event:

```json
{
  "time": 12.482,
  "instrument": "snare",
  "velocity": 0.81,
  "confidence": 0.93
}
```

The transcription engine must be wrapped behind an interface so the underlying model/library can later be replaced without rewriting the rest of the application.

Evaluate existing open-source drum-transcription libraries/models before building a model from scratch.

---

## 4. Timing model — critical architectural requirement

The audio timeline is the source of truth.

The system must not assume that a song has one perfectly fixed BPM and derive playback timing only from notation.

Every detected drum hit retains its absolute timestamp from the source audio.

Notation is generated from these events, but the playback cursor must synchronize against actual audio time.

This is intended to avoid the sync problems commonly experienced in notation players where the displayed score gradually drifts away from the recording.

The system should support:

- tempo estimation
- tempo changes
- timing deviations
- beat/grid quantization for notation

without losing the original timestamp.

---

## 5. Internal transcription data model

Create an application-owned intermediate representation rather than coupling the frontend directly to MusicXML, MIDI, or a specific ML model.

Suggested shape:

```ts
interface SongAnalysis {
  duration: number;
  tempoMap: TempoPoint[];
  measures: Measure[];
  events: DrumEvent[];
}

interface DrumEvent {
  id: string;
  time: number;
  instrument: DrumInstrument;
  velocity?: number;
  confidence?: number;
  measure?: number;
  beat?: number;
  subdivision?: number;
}

interface TempoPoint {
  time: number;
  bpm: number;
}
```

The timestamp must always remain available even after quantization.

---

## 6. Drum notation rules

The visual notation is an important part of the product and must follow consistent drum-score rules.

### Required MVP notation behaviour

- Standard five-line percussion staff.
- Bass drum displayed in the lower part of the staff.
- Snare displayed in its conventional staff position.
- Hi-hat/cymbals use appropriate x-shaped noteheads where supported.
- Open hi-hat must visually differ from closed hi-hat.
- Simultaneous drum hits must be vertically aligned.

### Stem direction — mandatory

All drum note stems should point **upward** in the generated notation, including:

- bass drum
- snare
- hi-hat
- cymbals
- toms

When multiple instruments occur at the same rhythmic position, they should visually share/group into the same upward stem or beam wherever the notation renderer allows it.

Examples:

- kick + hi-hat on beat 1 should appear as a vertically aligned chord-like drum event with an upward stem
- snare + hi-hat should be grouped on the same rhythmic position
- kick + snare + crash should be rendered together rather than as visually disconnected independent voices when practical

This behaviour should be implemented explicitly rather than relying on renderer defaults.

---

## 7. Notation renderer

Suggested frontend renderer:

- VexFlow

Alternative libraries may be used if they provide a materially better drum-notation implementation.

Renderer responsibilities:

- render measures
- position drum noteheads correctly
- force upward stems
- group simultaneous notes
- beam eighth/sixteenth notes where musically appropriate
- distinguish open and closed hi-hat
- display rests
- highlight the current playback position

The renderer should not own playback timing.

---

## 8. Player

Create a Songsterr-style practice view.

### Required controls

- play
- pause
- seek
- current time
- total duration
- master volume
- drum volume

Optional if trivial to add:

- playback speed

### Synchronization

The notation playhead should derive its position from the active audio playback clock.

Do not continuously advance the notation cursor using a separate independent timer.

The UI may use `requestAnimationFrame` for visual updates, but the current playback time should come from the audio engine.

---

## 9. Drum-volume control — mandatory MVP feature

The player must contain a dedicated **Drums** volume slider.

Example:

```text
Drums
[==========|----------] 50%
```

Behaviour:

- 100% = original drum stem at normal volume
- 50% = drums quieter while accompaniment remains unchanged
- 0% = drums muted completely

This allows the user to practise the generated score while hearing either reduced drums or no original drums at all.

Architecture:

```text
Accompaniment stem ──► gain ─┐
                             ├─► output
Drum stem ──────────► gain ──┘
```

The tracks must remain sample/timeline synchronized while changing volume.

Web Audio API is a suitable implementation choice.

---

## 10. Frontend

Suggested stack:

- Next.js
- TypeScript
- React
- VexFlow
- Web Audio API

The initial UI should be deliberately simple.

### Page 1 — input

```text
Drumscore

Generate playable drum notation from a song.

YouTube URL
[________________________________]

[ Generate drum score ]
```

### Processing state

Example:

```text
Downloading audio...
Separating drums...
Analysing drum track...
Building notation...
```

### Player view

```text
Song title

[ notation / measures ]
          │
          │ playback cursor

[◀] [Play/Pause] [▶]

Song   [====================]
Drums  [==========----------]
```

---

## 11. Backend

Suggested stack:

- Python
- FastAPI

Python is preferred for the processing service because most useful audio/ML libraries are Python based.

Suggested responsibilities:

```text
POST /api/jobs
GET  /api/jobs/{id}
GET  /api/jobs/{id}/analysis
GET  /api/jobs/{id}/audio/drums
GET  /api/jobs/{id}/audio/accompaniment
```

Processing should be job based because source extraction, stem separation and ML analysis may take significant time.

For the first version, a simple in-process/background job implementation is acceptable. The architecture should allow a real queue to be added later.

---

## 12. Suggested repository structure

```text
drumscore/
├── frontend/
│   ├── app/
│   ├── components/
│   │   ├── DrumScore.tsx
│   │   ├── Player.tsx
│   │   ├── DrumVolume.tsx
│   │   └── ProcessingStatus.tsx
│   ├── lib/
│   │   ├── audio/
│   │   ├── notation/
│   │   └── api/
│   └── types/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── audio/
│   │   ├── separation/
│   │   ├── transcription/
│   │   ├── notation/
│   │   └── models/
│   ├── tests/
│   └── requirements.txt / pyproject.toml
│
├── docs/
│   └── architecture.md
│
└── README.md
```

A monorepo is preferred for the MVP.

---

## 13. Suggested implementation tasks

### MVP-001 — Project foundation

Create:

- Next.js frontend
- FastAPI backend
- local development instructions
- basic frontend/backend connectivity

Acceptance criteria:

- both applications run locally
- frontend can call backend health endpoint

---

### MVP-002 — YouTube submission

Implement URL input and backend job creation.

Acceptance criteria:

- user can submit a valid URL
- a processing job is created
- invalid input produces a clear error

---

### MVP-003 — Audio extraction

Implement source-audio extraction.

Acceptance criteria:

- backend can produce an audio file from a supported YouTube URL
- failures are returned as job errors

---

### MVP-004 — Drum stem separation

Integrate stem separation.

Acceptance criteria:

- drum stem generated
- accompaniment stem generated
- both have matching duration/timeline

---

### MVP-005 — Drum transcription engine

Integrate an existing drum transcription solution behind an application-owned interface.

Acceptance criteria:

- returns timestamped drum hits
- supports kick, snare and hi-hat at minimum
- model-specific output is converted to internal `DrumEvent` objects

---

### MVP-006 — Beat and tempo mapping

Convert timestamped events into a notation-friendly rhythmic representation.

Acceptance criteria:

- tempo is estimated
- events can be assigned to measures/beats/subdivisions
- original timestamps remain unchanged and available

---

### MVP-007 — Drum notation rendering

Build the drum-score component.

Acceptance criteria:

- displays standard percussion staff
- renders kick, snare and hi-hat correctly
- open/closed hi-hat are visually distinguishable
- simultaneous hits align vertically
- **all note stems point upward**
- simultaneous instruments share/group on an upward stem where supported
- eighth/sixteenth grouping is readable

---

### MVP-008 — Synchronized playback

Create the notation/audio playback engine.

Acceptance criteria:

- play/pause works
- seeking works
- playback cursor follows source-audio time
- cursor remains synchronized across an entire song

---

### MVP-009 — Drum-volume mixer

Implement independent drum volume.

Acceptance criteria:

- drum stem and accompaniment play simultaneously
- drum-volume slider supports 0–100%
- 0% completely mutes original drums
- changing volume does not affect synchronization
- accompaniment volume remains unchanged

---

### MVP-010 — End-to-end workflow

Connect the complete flow.

```text
YouTube URL
    ↓
Audio extraction
    ↓
Stem separation
    ↓
Drum transcription
    ↓
Tempo / beat mapping
    ↓
Internal score representation
    ↓
Notation renderer
    ↓
Synchronized practice player
```

Acceptance criteria:

A user can paste a URL, wait for processing, open the generated score, press play, see synchronized drum notation and lower/mute the source drums.

---

### MVP-011 — Tests and hardening

Add tests for the most important logic.

Minimum coverage areas:

- transcription mapping
- timestamp preservation
- beat quantization
- notation grouping
- upward stem rules
- simultaneous-hit rendering model
- drum-volume mixer state
- API job lifecycle

Also review and address everything logged in `TECHNICAL_DEBT.md` — items
found along the way during earlier MVP tasks that were deliberately
deferred rather than fixed on the spot.

---

## 14. Definition of Done for MVP

The MVP is complete when a user can:

1. Open Drumscore.
2. Paste a supported YouTube URL.
3. Generate a drum transcription for the song.
4. View it as readable drum notation.
5. Press play and hear the song.
6. See the current position move through the score in sync with the recording.
7. See kick/snare/hi-hat and other detected drums in correct vertical positions.
8. See all drum-note stems pointing upward.
9. See simultaneous hits grouped/aligned together.
10. Lower the source drum volume.
11. Completely mute the source drums and practise along with the accompaniment.

The goal is not perfect professional transcription accuracy in version 1. The goal is a useful, stable practice experience whose architecture allows transcription quality to improve independently.

---

## 15. Explicitly out of scope for the first MVP

Do not allow these features to delay the first usable version:

- user accounts
- cloud library
- mobile app
- collaboration
- social features
- advanced score editor
- manual note entry
- PDF export
- MusicXML export
- MIDI export
- e-drum MIDI input
- scoring the user's performance
- Guitar Hero-style judgement
- multiple difficulty levels
- automatic simplification
- polished production deployment

These are candidates for later phases.

---

## 16. Future roadmap

After the MVP works reliably, likely next features are:

1. Manual score correction/editor.
2. MusicXML/PDF export.
3. E-drum MIDI input.
4. Real-time judgement of player timing.
5. Loop selected measures.
6. Count-in and metronome.
7. Adjustable playback speed without pitch shift.
8. Automatic score simplification / difficulty levels.
9. Saved songs and user library.
10. Improved transcription models and confidence-driven correction UI.

---

## 17. Important engineering principles

1. **Audio timestamps are the source of truth.**
2. Keep transcription, notation and playback as separate modules.
3. Never couple the application to a single ML/transcription library.
4. Preserve raw detected timestamps after quantization.
5. Keep drum-stem volume independently controllable.
6. Force the agreed drum-notation style instead of relying on renderer defaults.
7. Build the simplest working vertical slice before optimizing accuracy.
8. Prefer replaceable interfaces around experimental ML/audio components.
