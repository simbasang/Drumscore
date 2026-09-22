# Diagnostic song fixtures

Small, deterministic, synthetic drum-track fixtures used by EPIC 1
(Instrumentation & Stabilization, #28) to reproduce timing-related issues
without depending on real (copyrighted) recordings.

## Why synthetic

Every fixture's audio is generated at test time by `diagnostic_songs.py`
from known event times - nothing is committed as a binary audio asset.
This keeps the corpus:

- **deterministic**: same seed in, same waveform out, every run.
- **copyright-safe**: no real recordings are used or distributed.
- **small**: fixtures are seconds long and exist only in memory or in a
  test's `tmp_path` while a test runs.

## Usage

```python
from tests.fixtures.diagnostic_songs import get_diagnostic_song

song = get_diagnostic_song("intro_count_in")
audio = song.generate_audio()          # np.ndarray, mono, song.sample_rate Hz
song.write_wav(tmp_path / "song.wav")  # for tests that need a real audio file

song.tempo_bpm                # ground-truth tempo
song.downbeat_offset_seconds  # ground-truth offset of measure 1 / beat 1
song.expected_hits            # tuple[ExpectedHit], ground truth (time, instrument)
```

`list_diagnostic_songs()` returns every fixture; `get_diagnostic_song(key)`
raises `KeyError` for an unknown key.

## Fixtures

| key | timing case | tempo | downbeat offset | what it targets |
|---|---|---|---|---|
| `steady_4_4` | steady 4/4 | 120 BPM | 0.0s | Baseline: constant-tempo rock beat, first downbeat at t=0. |
| `intro_count_in` | intro silence / count-in | 120 BPM | 2.5s | 0.5s silence plus a 1-measure hi-hat count-in before the first real downbeat - exercises the fixed-grid phase-alignment gap in `quantize_events` (see `TECHNICAL_DEBT.md`, "Quantization grid isn't phase-aligned to the beat"). |
| `dense_fill` | dense 16ths / fills | 120 BPM | 0.0s | Two measures of groove, then a full measure of straight 16th-note snare/tom fill resolving on a crash+kick downbeat - exercises dense event rates and simultaneous-hit grouping. |
| `timing_variation` | timing variation | 120 BPM | 0.0s | Same groove as `steady_4_4`, every hit shifted by a deterministic +/-20ms seeded jitter - simulates a live, non-quantized performance. |

Every fixture's `expected_hits` is the ground truth: `(time, instrument)`
pairs the synthesized audio was built from. Consumers (tempo estimation,
quantization, transcription-diagnostics tests) compare pipeline output
against this ground truth instead of a real recording's unknown,
unverifiable transcription.

## Adding a new fixture

1. Add a `_build_<name>()` function returning a `DiagnosticSong`, using
   `steady_rock_beat(...)` or building `ExpectedHit`s directly.
2. Register it in `_BUILDERS` in `diagnostic_songs.py`.
3. Document it in the table above.
