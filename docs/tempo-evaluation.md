# Tempo and beat evaluation (V1-036, #113)

How we measure whether the beat map sits on the musical beat, and what the
Beat This! engine achieves on real songs.

## Method

- **Fixtures:** eight commercial recordings in `app/tempo_benchmark.py`
  (`REAL_TEMPO_SONGS`), chosen to cover the classic pulse-level traps:
  slow (75), fast (177), shuffle, 6/8, and straight 4/4 songs. Reference
  tempos are published values cross-checked across getsongbpm, songbpm,
  tunebat and Hooktheory (CCR also against the product owner's reference
  MIDI). Compound meters count the dotted quarter. Audio is never
  committed.
- **Metric:** `classify_tempo`: correct when within ±4% of the reference,
  otherwise it names the error (`double`, `half`, `three_halves`,
  `two_thirds`, `other`).
- **Run it:**

  ```
  cd backend
  uv run python -m app.tempo_benchmark fetch <dir>   # yt-dlp + Demucs, once per song
  uv run python -m app.tempo_benchmark run <dir>     # exit 1 unless 8/8 correct
  ```

## Root cause of the MVP behaviour

1. `LibrosaTempoEstimator` chose between 0.5×, ⅔×, 1×, 1.5× and 2× of
   librosa's tempo by the mean phase error of onsets against a grid
   anchored at t=0. On a real song, a tempo error of a fraction of a BPM
   accumulates over minutes, so onset phases spread uniformly and every
   candidate scores ≈0.25, the value for random onsets. The choice was
   noise, and it overrode librosa's correct estimate (CCR: 114.8 →
   229.7). Its unit tests only used perfect synthetic grids from t=0.
2. `LibrosaBeatDetector` laid one constant-tempo grid over the whole song.
   Even at the right octave it drifted 1.5 s (CCR) and 1.9 s (Rick
   Astley) from the tracked beats by the end of the song, about three
   beats.

## Results (detected BPM; ✘ = outside ±4%)

| Song | Ref | MVP estimator | librosa tracker | Beat This!, drum stem | **Beat This!, mix (shipped)** |
|---|---|---|---|---|---|
| CCR — Have You Ever Seen the Rain | 116 | 229.7 ✘ 2× | 117.5 | 115.4 | **116.5** |
| Rick Astley — Never Gonna Give You Up | 113 | 57.4 ✘ ½× | 112.3 | 115.4 | **113.2** |
| Eagles — Hotel California | 75 | 295.3 ✘ | 73.8 | 73.2 | **73.6** |
| Ramones — Blitzkrieg Bop | 177 | 175.2 | 89.1 ✘ ½× | 176.5 | **176.5** |
| Tears for Fears — Everybody Wants to Rule the World | 112 | 224.7 ✘ 2× | 112.3 | 166.7 ✘ 1.5× | **111.1** |
| Queen — We Are the Champions (6/8) | 64 | 146.3 ✘ | 63.0 | 63.8 | **63.5** |
| AC/DC — Back in Black | 93 | 187.9 ✘ 2× | 95.7 | 93.7 | **94.5** |
| Michael Jackson — Billie Jean | 117 | 234.9 ✘ 2× | 117.5 | 115.4 | **116.5** |
| **Correct** | | **1/8** | **7/8** | **7/8** | **8/8** |

The shipped column is `BeatThisBeatDetector` end to end: the mix rebuilt
from both stems, regularization, and tempo from 4-beat spans. An earlier
drum-stem backbeat heuristic (kick/snare alternation at the candidate
pulse) scored 3/5 and was dropped.

## Beat-sequence regularization

The tracker's raw beats are not always one entry per beat. On the mixes,
Hotel California had two ~30 s guitar sections tracked in double time,
Queen's drumless piano intro was tracked at the triplet level, and Rick
Astley and Tears for Fears had isolated spurious beats, plus 1–2 skipped
beats elsewhere. Quantization, measure numbering and the metronome all
assume one entry per beat, so each glitch would shift every later bar.
`app/beat_regularization.py` walks the detections at the song's typical
period (drift of up to ±25% allowed), keeps the detection nearest each
expected beat and divides gaps evenly. After it, irregular intervals
(<0.7× or >1.3×) are 0 on six songs, 3 on Tears for Fears and 10 on Queen.

## Downbeats (measure phase)

The meter stays 4/4: the frontend grid and the quantizer hardcode four
beats per measure. The tracker's downbeats only choose which beat is beat
1, by a majority vote over the song. Share of tracker downbeats that land
on our beat 1: CCR 100%, Blitzkrieg Bop 100%, Back in Black 99%, Billie
Jean 89%, Hotel California 80%, Rick Astley 60%, Tears for Fears 43%,
Queen (6/8) 28%. The low values come from sections where the tracker hears
2-beat bars or shifts by half a bar. A single global phase cannot follow
that; see TECHNICAL_DEBT.md, "Measure phase is one global choice".

## Limitations

- Tempo changes of more than ±25% of the typical tempo inside one song are
  forced back to the typical level by regularization.
- 6/8 and 12/8 songs get the right pulse but are still notated in a 4/4
  sixteenth grid.
- Eight songs is a small set; it covers the known failure classes, not
  every genre.
