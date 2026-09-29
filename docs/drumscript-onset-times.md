# DrumScript onset times (V1-038)

## Problem

`drumscript.transcribe()` ends by building its own score:
`notation_generator/score_builder.py` snaps every event to a 16th-note grid at
DrumScript's single estimated tempo and overwrites `event["time_sec"]` in
place, and `transcribe()` returns those same dicts. The runner read
`time_sec` from them, so since the MVP every DrumScript event's "source time"
was a grid time. On CCR, 452 of 554 intervals between non-kick onsets were
exactly 0.2554–0.2555 s, one DrumScript eighth note at ~117.4 BPM. A single
tempo grid drifts against a human performance, so events, click-to-seek and
the playhead landed on grid times instead of the hits.

## Change

`drumscript_runner/run_transcription.py` runs the steps `transcribe()` runs
before building its score, with the same arguments: `load_audio(sr=SAMPLE_RATE)`,
`normalise_audio`, `detect_onsets`, `classify_events`. It skips DrumScript's
tempo estimate and `build_score` (and with it the PDF/JSON/MIDI side files).
`build_score` only rewrites `time_sec`, so events and instruments are
identical to before; only their times changed. Quantization stays in
Drumscore's timing layer. `PIPELINE_VERSION` went to 4 so cached
transcriptions from the old runner are not reused.

## Measurements

Both on the production transcriber
(`KickReplacingTranscriber(DrumScriptTranscriber(), LowBandKickDetector())`),
before and after the change. Kicks come from `LowBandKickDetector` and are
unaffected by construction.

**MDB Drums**, all 23 songs, `uv run python -m app.drum_benchmark run <dir>
production <condition>` (method: docs/kick-detection-evaluation.md). F1 per
group, 50 ms tolerance; detection counts are the same before and after.

| group | demucs (production path) | drum_only |
|---|---|---|
| kick | 0.87 → 0.87 | 0.92 → 0.92 |
| snare | 0.49 → 0.64 | 0.50 → 0.66 |
| hi-hat | 0.43 → 0.60 | 0.44 → 0.61 |
| cymbals | 0.09 → 0.11 | 0.19 → 0.28 |
| toms | 0.00 → 0.00 | 0.00 → 0.00 |

Held-out split only (11 songs, demucs): snare 0.46 → 0.62, hi-hat 0.29 →
0.46, cymbals 0.08 → 0.10.

**CCR "Have You Ever Seen the Rain"** (`bO28lB1uwp4`), V1-037 Demucs drum
stem, against the product owner's reference MIDI (alignment method:
docs/RELEASE_REPORT_V1.md). 986 events before and after.

| | before | after |
|---|---|---|
| onsets, instrument-agnostic F1 | 0.68 | 0.91 |
| hi-hat (open+closed merged) F1 | 0.64 | 0.88 |
| closed hi-hat F1 | 0.52 | 0.73 |
| open hi-hat F1 | 0.26 | 0.35 |
| snare F1 | 0.39 | 0.56 |
| crash F1 | 0.28 | 0.41 |
| kick F1 | 0.62 | 0.65 |
| most common non-kick interval | 0.2554 s (364 of 553) | 0.2583 s (34 of 553) |

The kick change on CCR comes from the MIDI alignment, which is fitted to all
onsets and now fits better; the kick events themselves are identical.

## What remains

Classification, not timing, now limits snare/hi-hat/cymbal accuracy:
MDB hi-hat precision is 0.46 (DrumScript emits about twice as many hi-hats as
the reference), open hi-hat recall on CCR is 0.23, and DrumScript emits no
toms. See `TECHNICAL_DEBT.md`, "Generated notation doesn't look/read quite
right yet".
