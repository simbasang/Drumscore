"""Real-song tempo benchmark: does the beat detector find the musical
pulse (no 2x / 0.5x / 1.5x errors) on labelled recordings?

    uv run python -m app.tempo_benchmark fetch <dir>   # yt-dlp + Demucs, once
    uv run python -m app.tempo_benchmark run <dir>     # exit 1 unless all correct

Audio is never committed: `fetch` stores `<dir>/<video id>/drums.wav` and
`accompaniment.wav` locally. Method and results: docs/tempo-evaluation.md.
"""

import dataclasses
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence, TextIO

from app.audio_extraction import AudioExtractor
from app.beat_detection import BeatDetector
from app.beat_this_beat_detector import tempo_from_beats
from app.media_source import MediaSourceValidator
from app.stem_separation import StemSeparator

TEMPO_TOLERANCE = 0.04
# Absorbs float rounding so a tempo exactly at the tolerance counts as inside.
_EPSILON = 1e-9

# Pulse-level errors, checked in this order after "correct".
_PULSE_ERRORS: tuple[tuple[str, float], ...] = (
    ("double", 2.0),
    ("half", 0.5),
    ("three_halves", 1.5),
    ("two_thirds", 2.0 / 3.0),
)


@dataclasses.dataclass(frozen=True)
class TempoFixture:
    video_id: str
    title: str
    reference_bpm: float
    meter: str
    sources: str


# References are published tempos, cross-checked across sources (issue #113).
# Compound meters count the dotted-quarter pulse.
REAL_TEMPO_SONGS: tuple[TempoFixture, ...] = (
    TempoFixture("bO28lB1uwp4", "CCR - Have You Ever Seen the Rain", 116.0, "4/4", "getsongbpm/tunebat 117; product owner's MIDI 115"),
    TempoFixture("dQw4w9WgXcQ", "Rick Astley - Never Gonna Give You Up", 113.0, "4/4", "getsongbpm/tunebat 112-114"),
    TempoFixture("dLl4PZtxia8", "Eagles - Hotel California", 75.0, "4/4", "getsongbpm/songbpm 75 (some list 148)"),
    TempoFixture("skdE0KAFCEA", "Ramones - Blitzkrieg Bop", 177.0, "4/4", "getsongbpm/songbpm/tunebat 176-180"),
    TempoFixture("aGCdLKXNF3w", "Tears for Fears - Everybody Wants to Rule the World", 112.0, "4/4 shuffle", "getsongbpm/songbpm 112"),
    TempoFixture("04854XqcfCY", "Queen - We Are the Champions", 64.0, "6/8", "Hooktheory 193 eighths = 64.3 dotted quarters"),
    TempoFixture("pAgnJDJN4VA", "AC/DC - Back in Black", 93.0, "4/4", "getsongbpm/songbpm 92-94"),
    TempoFixture("Zi_XLOBDo_Y", "Michael Jackson - Billie Jean", 117.0, "4/4", "getsongbpm/tunebat 116-117"),
)


@dataclasses.dataclass(frozen=True)
class TempoResult:
    fixture: TempoFixture
    detected_bpm: float | None
    verdict: str


def classify_tempo(detected: float, reference: float, tolerance: float = TEMPO_TOLERANCE) -> str:
    """"correct" within tolerance of the reference, else the pulse-level
    error it matches ("double", "half", "three_halves", "two_thirds"),
    else "other"."""
    if abs(detected / reference - 1) <= tolerance + _EPSILON:
        return "correct"
    for name, ratio in _PULSE_ERRORS:
        if abs(detected / (reference * ratio) - 1) <= tolerance + _EPSILON:
            return name
    return "other"


def evaluate(
    fixtures: Sequence[TempoFixture], detect_bpm: Callable[[TempoFixture], float | None]
) -> list[TempoResult]:
    results = []
    for fixture in fixtures:
        bpm = detect_bpm(fixture)
        verdict = "missing" if bpm is None else classify_tempo(bpm, fixture.reference_bpm)
        results.append(TempoResult(fixture=fixture, detected_bpm=bpm, verdict=verdict))
    return results


def _stem_paths(root: Path, fixture: TempoFixture) -> tuple[Path, Path]:
    return root / fixture.video_id / "drums.wav", root / fixture.video_id / "accompaniment.wav"


def fetch_stems(
    fixtures: Sequence[TempoFixture],
    root: Path,
    validator: MediaSourceValidator,
    extractor: AudioExtractor,
    separator: StemSeparator,
) -> None:
    """Downloads and separates each song not already under root."""
    for fixture in fixtures:
        drums, accompaniment = _stem_paths(root, fixture)
        if drums.exists() and accompaniment.exists():
            continue
        drums.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as scratch:
            source = validator.parse(f"https://www.youtube.com/watch?v={fixture.video_id}")
            audio = extractor.extract(source, Path(scratch) / "source")
            stems = separator.separate(audio.audio_path, Path(scratch) / "stems")
            shutil.copyfile(stems.drums_path, drums)
            shutil.copyfile(stems.accompaniment_path, accompaniment)


def run_benchmark(fixtures: Sequence[TempoFixture], root: Path, detector: BeatDetector, out: TextIO) -> int:
    """Prints one row per song; returns 0 only when every tempo is correct."""

    def detect_bpm(fixture: TempoFixture) -> float | None:
        drums, accompaniment = _stem_paths(root, fixture)
        if not (drums.exists() and accompaniment.exists()):
            return None
        return tempo_from_beats(detector.detect(drums, accompaniment))

    results = evaluate(fixtures, detect_bpm)
    for result in results:
        detected = "-" if result.detected_bpm is None else f"{result.detected_bpm:.1f}"
        out.write(
            f"{result.fixture.video_id}  ref {result.fixture.reference_bpm:>5.1f}  detected {detected:>6}  "
            f"{result.verdict:<12}  {result.fixture.title}\n"
        )
    correct = sum(result.verdict == "correct" for result in results)
    out.write(f"{correct}/{len(results)} correct (tolerance {TEMPO_TOLERANCE:.0%})\n")
    return 0 if correct == len(results) else 1


def main(argv: Sequence[str]) -> int:  # pragma: no cover - wires real engines; logic tested above
    if len(argv) != 2 or argv[0] not in ("fetch", "run"):
        print(__doc__)
        return 2
    root = Path(argv[1])
    if argv[0] == "fetch":
        from app.demucs_stem_separator import DemucsStemSeparator
        from app.youtube_audio_extractor import YtDlpAudioExtractor
        from app.youtube_source import YouTubeSourceValidator

        fetch_stems(REAL_TEMPO_SONGS, root, YouTubeSourceValidator(), YtDlpAudioExtractor(), DemucsStemSeparator())
        return 0
    from app.beat_this_beat_detector import BeatThisBeatDetector

    return run_benchmark(REAL_TEMPO_SONGS, root, BeatThisBeatDetector(), sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
