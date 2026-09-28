# Kick detection evaluation (V1-037, #114)

## Problem

In the V1-035 release pass, CCR "Have You Ever Seen the Rain" produced 17
kicks where the reference MIDI has 263 (kick F1 0.09 after alignment). The raw
DrumScript output already had only 17, so the loss was inside the engine.

## Root cause

DrumScript's onset detector finds the kicks; its classifier discards them.
`classify_events` (installed `drumscript/drum_classifier/classify.py`) calls
an onset a kick only if at least 32% of the mean magnitude spectrum of a
200 ms slice lies below 150 Hz, and the spectral peak is at 40–140 Hz. On a
real drum stem, hi-hats, snare and cymbals ringing over the kick dilute that
whole-spectrum ratio.

Measured on MDB Drums drum-only tracks: an onset exists within 50 ms of 100%,
100% and 90% of the labelled kicks (80sRock, Britpop, Punk), but only
15/63, 19/48 and 12/73 are classified as kicks; the median ratio at real kicks
is 0.22–0.32. On the CCR drum stem the 99th percentile of the ratio over all
555 onsets is 0.38, so the rule almost never fires.

Changing thresholds inside DrumScript would mean patching a third-party
package, and the neural alternatives are licence-blocked
(docs/transcription-engine-evaluation.md), so kicks get their own detector.

## Change

`LowBandKickDetector` (`backend/app/kick_detection.py`) works on the drum
stem only:

1. Peak-normalise, STFT (1024 samples, hop 256), sum magnitudes in 30–150 Hz.
2. Onset strength = positive first difference of `log1p(100 · band)`;
   `librosa.util.peak_pick` with an absolute threshold `delta = 1.0` and at
   least 80 ms between kicks.
3. Keep a peak only if the low band is at least 0.3 × the 150–1000 Hz band in
   the following ~23 ms. Without this guard, snares (whose body also has
   low-band energy) were most false kicks: in Disco every snare fired.

`KickReplacingTranscriber` takes every kick from the detector and every other
instrument from DrumScript unchanged. DrumScript's own kicks are dropped:
merged with the detector's (union) they cost precision (held-out kick F1 0.76
vs 0.88). DrumScript's full, unmodified output is stored as the
`engine_transcription` artifact next to `raw_transcription`. Detector kicks have
`provenance: "kick_detector"` and `confidence: null`: flux strength is not a
calibrated probability.

The 1024-sample window is deliberate: log flux peaks as soon as the window's
leading edge reaches the kick, so kicks are reported early. The median offset
against MDB labels is −7 ms (2048 samples: −16 ms), well inside the 50 ms
matching tolerance and a sixteenth note at any tempo.

## Method

- **Data:** [MDB Drums](https://github.com/CarlSouthall/MDBDrums), 23
  MedleyDB songs (rock, pop, jazz, funk, metal …) with hand-labelled kick,
  snare, hi-hat, tom and cymbal onsets. CC BY-NC-SA 4.0, fetched locally,
  never committed.
- **Conditions:** `demucs` is the production path (full mix → Demucs → drum
  stem); `drum_only` is the original isolated drum recording.
- **Scoring:** `app/benchmark.py` matching (greedy, per instrument group,
  50 ms), counts pooled over songs before computing P/R/F1. Open/closed
  hi-hat are merged, and so are crash/ride, because MDB's labels don't split
  them.
- **Split:** songs sorted by name; even positions are the tune split (12),
  odd the held-out split (11). All parameters were chosen on the tune split;
  held-out numbers are the claim.
- **Reproduce:** `uv run python -m app.drum_benchmark fetch <dir>`, then
  `run <dir> drumscript|production demucs|drum_only`.

### Tuning (tune split, demucs)

Grid: `delta ∈ {0.75, 1.0, 1.5}` × ratio `∈ {0.2, 0.3, 0.5, 0.75, 1.0}`,
union vs replace (plus an earlier sweep of band edge 120/150 Hz and the
minimum interval 60/80/100 ms, which barely mattered). Best tune F1 was
delta 1.0, ratio 0.75 (0.89), versus 0.86 at ratio 0.3.

**Ratio 0.3 was chosen over 0.75 because of CCR**, not the tune split: CCR's
real kicks have a median low/mid ratio of 0.63 (10th percentile 0.17), while
MDB's modern recordings have 2.75 (10th percentile 0.87). At 0.75 CCR kick
recall drops to 0.16. 0.3 is still well above MDB's false-kick median (0.13)
and costs 0.03 F1 on MDB. CCR is not labelled ground truth (see below), so this
is a judgement for thin-sounding recordings, stated here openly.

## Results

Kick, pooled (DrumScript today → this change):

| Split | Condition | P | R | F1 |
|---|---|---|---|---|
| held-out (11) | demucs | 0.55 → 0.87 | 0.37 → 0.89 | **0.45 → 0.88** |
| held-out (11) | drum_only | 0.75 → 0.89 | 0.22 → 0.96 | 0.35 → 0.93 |
| tune (12) | demucs | 0.63 → 0.83 | 0.48 → 0.90 | 0.54 → 0.86 |
| all (23) | demucs | 0.59 → 0.85 | 0.42 → 0.89 | 0.49 → 0.87 |

Other groups are unchanged by construction and measured identical (all 23,
demucs): snare F1 0.49, hi-hat 0.43, cymbals 0.09, toms 0.00 (DrumScript
emits no toms at all on these songs). These non-kick figures were measured on
DrumScript's grid-quantized times; with its source onset times (V1-038) they
are snare 0.64, hi-hat 0.60, cymbals 0.11 (docs/drumscript-onset-times.md).

Per-song kick F1, demucs (DrumScript → this change): 80sRock 0.93 → 0.99,
Beatles 0.76 → 0.61, BebopJazz 0.06 → 0.60, Britpop 0.52 → 0.78, CoolJazz
0.12 → 0.32, Country1 0.45 → 0.93, Disco 0.67 → 0.98, FreeJazz 0.16 → 0.80,
FunkJazz 0.31 → 0.93, FusionJazz 0.67 → 0.92, Gospel 0.67 → 0.93, Grunge
0.67 → 0.89, Hendrix 0.57 → 0.98, LatinJazz 0.00 → 0.98, ModalJazz 0.00 →
0.71, Punk 0.30 → 0.81, Reggae 0.71 → 0.97, Rock 0.56 → 0.89, Rockabilly
0.87 → 0.98, Shadows 0.00 → 0.98, SpeedMetal 0.32 → 0.98, SwingJazz 0.38 →
0.93, Zeppelin 0.32 → 0.95.

### CCR (secondary check)

Against the product owner's reference MIDI, with the alignment method from
docs/RELEASE_REPORT_V1.md (a fan-made arrangement, not ground truth):

| | kicks detected | P | R | F1 |
|---|---|---|---|---|
| DrumScript | 16 | 0.75 | 0.05 | 0.09 |
| this change | 284 | 0.63 | 0.68 | **0.65** |

Snare (0.56) and merged hi-hat (0.88) are unchanged. These two were
measured on DrumScript's raw onsets; the shipped pipeline gets
grid-quantized DrumScript times (0.39 / 0.65 on CCR, #118; see
`docs/RELEASE_REPORT_V1.md`).

## Limitations

- **Soft kicks** whose low-band rise stays under the threshold are missed
  (Beatles: 23/47 found, DrumScript had more; CoolJazz's feathered jazz kick).
- **Thin, vintage kicks** (CCR) sit close to the ratio guard; recall 0.68 there.
- **Low-frequency bleed** into the Demucs stem (bass, low toms) can still
  produce false kicks; there is no per-recording adaptation.
- **Snare, hi-hat, toms and cymbals** remain DrumScript's and are weak on real
  audio (see TECHNICAL_DEBT.md).
- MDB's labels cannot measure open/closed hi-hat or crash/ride. IDMT-SMT-Drums
  was not added (CC BY-NC-ND, drum-only loops).
