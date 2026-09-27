"""Real-audio transcription benchmark on MDB Drums: per-instrument-group
precision/recall/F1 against hand-labelled hits in 23 real songs.

    uv run python -m app.drum_benchmark fetch <dir>
    uv run python -m app.drum_benchmark run <dir> [drumscript|production] [demucs|drum_only]

`fetch` downloads each song's full mix, drum-only track and class
annotations from github.com/CarlSouthall/MDBDrums (CC BY-NC-SA 4.0) and runs
the full mix through Demucs, as production does. Nothing is committed.
`run` scores the Demucs drum stem ("demucs", the production path) or the
original drum-only track ("drum_only"). Parameters are tuned on the tune
split only; the held-out split is what docs/kick-detection-evaluation.md
reports.
"""

import dataclasses
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Sequence, TextIO

from app.benchmark import DEFAULT_MATCH_TOLERANCE_SECONDS, MatchCounts, match_hits
from app.stem_separation import StemSeparator
from app.transcription import DrumEvent, DrumInstrument, DrumTranscriber

MDB_BASE_URL = "https://raw.githubusercontent.com/CarlSouthall/MDBDrums/master/MDB%20Drums"

MDB_SONGS: tuple[str, ...] = tuple(
    f"MusicDelta_{name}"
    for name in (
        "80sRock", "Beatles", "BebopJazz", "Britpop", "CoolJazz", "Country1", "Disco", "FreeJazz",
        "FunkJazz", "FusionJazz", "Gospel", "Grunge", "Hendrix", "LatinJazz", "ModalJazz", "Punk",
        "Reggae", "Rock", "Rockabilly", "Shadows", "SpeedMetal", "SwingJazz", "Zeppelin",
    )
)

# MDB's six-class labels hold no open/closed hi-hat or crash/ride split, so
# DrumInstrument values are scored in the groups the labels can support.
GROUPS: dict[str, frozenset[DrumInstrument]] = {
    "kick": frozenset({DrumInstrument.KICK}),
    "snare": frozenset({DrumInstrument.SNARE}),
    "hihat": frozenset({DrumInstrument.HIHAT_CLOSED, DrumInstrument.HIHAT_OPEN}),
    "toms": frozenset({DrumInstrument.TOM_LOW, DrumInstrument.TOM_MID, DrumInstrument.TOM_HIGH}),
    "cymbals": frozenset({DrumInstrument.CRASH, DrumInstrument.RIDE}),
}

# "OT" (other percussion) has no DrumInstrument and is not scored.
_MDB_CLASSES = {"KD": "kick", "SD": "snare", "HH": "hihat", "TT": "toms", "CY": "cymbals"}

_CONDITION_FILES = {"demucs": "drums.wav", "drum_only": "drum_only.wav"}


@dataclasses.dataclass(frozen=True)
class LabelledHit:
    time: float
    group: str


def parse_annotations(text: str) -> list[LabelledHit]:
    hits = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] in _MDB_CLASSES:
            hits.append(LabelledHit(float(fields[0]), _MDB_CLASSES[fields[1]]))
    return hits


def evaluate_song(
    events: Sequence[DrumEvent],
    hits: Sequence[LabelledHit],
    tolerance_seconds: float = DEFAULT_MATCH_TOLERANCE_SECONDS,
) -> dict[str, MatchCounts]:
    result = {}
    for group, instruments in GROUPS.items():
        predicted = [event for event in events if event.instrument in instruments]
        expected = [hit for hit in hits if hit.group == group]
        true_positives, unmatched_predicted, unmatched_expected = match_hits(predicted, expected, tolerance_seconds)
        result[group] = MatchCounts.from_counts(true_positives, len(unmatched_predicted), len(unmatched_expected))
    return result


def pool(results: Iterable[dict[str, MatchCounts]]) -> dict[str, MatchCounts]:
    totals = {group: [0, 0, 0] for group in GROUPS}
    for result in results:
        for group, counts in result.items():
            total = totals[group]
            total[0] += counts.true_positives
            total[1] += counts.false_positives
            total[2] += counts.false_negatives
    return {group: MatchCounts.from_counts(*total) for group, total in totals.items()}


def split_songs(songs: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(tune, held_out): alternate songs in name order."""
    ordered = sorted(songs)
    return tuple(ordered[0::2]), tuple(ordered[1::2])


def _song_dir(root: Path, song: str) -> Path:
    return root / song


def fetch_songs(
    songs: Sequence[str],
    root: Path,
    download: Callable[[str, Path], None],
    separator: StemSeparator,
) -> None:
    """Downloads and separates each song not already under root."""
    for song in songs:
        song_dir = _song_dir(root, song)
        if (song_dir / "drums.wav").exists() and (song_dir / "annotations.txt").exists():
            continue
        song_dir.mkdir(parents=True, exist_ok=True)
        download(f"{MDB_BASE_URL}/audio/full_mix/{song}_MIX.wav", song_dir / "mix.wav")
        download(f"{MDB_BASE_URL}/audio/drum_only/{song}_Drum.wav", song_dir / "drum_only.wav")
        with tempfile.TemporaryDirectory() as scratch:
            stems = separator.separate(song_dir / "mix.wav", Path(scratch) / "stems")
            shutil.copyfile(stems.drums_path, song_dir / "drums.wav")
        # Written last: its presence marks the song as complete.
        download(f"{MDB_BASE_URL}/annotations/class/{song}_class.txt", song_dir / "annotations.txt")


def _write_pooled(label: str, results: list[dict[str, MatchCounts]], out: TextIO) -> None:
    out.write(f"== {label} ({len(results)} songs)\n")
    out.write(f"{'group':<8} {'ref':>5} {'det':>5}     P     R    F1\n")
    for group, counts in pool(results).items():
        reference = counts.true_positives + counts.false_negatives
        detected = counts.true_positives + counts.false_positives
        out.write(
            f"{group:<8} {reference:>5} {detected:>5}  {counts.precision:.2f}  {counts.recall:.2f}  {counts.f1:.2f}\n"
        )


def run_benchmark(
    songs: Sequence[str],
    root: Path,
    transcriber: DrumTranscriber,
    condition: str,
    out: TextIO,
) -> int:
    """Prints per-song kick/snare/hi-hat F1 and pooled tables for the tune,
    held-out and full sets. A measurement, not a gate: always returns 0."""
    results: dict[str, dict[str, MatchCounts]] = {}
    for song in sorted(songs):
        song_dir = _song_dir(root, song)
        annotations = song_dir / "annotations.txt"
        if not annotations.exists():
            out.write(f"{song}: missing\n")
            continue
        events = transcriber.transcribe(song_dir / _CONDITION_FILES[condition])
        result = evaluate_song(events, parse_annotations(annotations.read_text()))
        results[song] = result
        out.write(
            f"{song:<24} kick {result['kick'].f1:.2f}  snare {result['snare'].f1:.2f}  hihat {result['hihat'].f1:.2f}\n"
        )

    tune, held_out = split_songs(songs)
    for label, subset in (("tune", tune), ("held-out", held_out), ("all", tuple(songs))):
        _write_pooled(label, [results[song] for song in subset if song in results], out)
    return 0


def main(argv: Sequence[str]) -> int:  # pragma: no cover - wires real engines and network; logic tested above
    if len(argv) < 2 or argv[0] not in ("fetch", "run"):
        print(__doc__)
        return 2
    root = Path(argv[1])
    if argv[0] == "fetch":
        import urllib.request

        from app.demucs_stem_separator import DemucsStemSeparator

        fetch_songs(MDB_SONGS, root, lambda url, path: urllib.request.urlretrieve(url, path), DemucsStemSeparator())
        return 0
    engine = argv[2] if len(argv) > 2 else "production"
    condition = argv[3] if len(argv) > 3 else "demucs"
    from app.drumscript_transcriber import DrumScriptTranscriber

    transcriber: DrumTranscriber = DrumScriptTranscriber()
    if engine == "production":
        from app.kick_replacing_transcriber import KickReplacingTranscriber
        from app.kick_detection import LowBandKickDetector

        transcriber = KickReplacingTranscriber(transcriber, LowBandKickDetector())
    return run_benchmark(MDB_SONGS, root, transcriber, condition, sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
