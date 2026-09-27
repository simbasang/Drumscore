import io
from pathlib import Path

import pytest

from app.benchmark import MatchCounts
from app.drum_benchmark import (
    GROUPS,
    MDB_SONGS,
    LabelledHit,
    evaluate_song,
    fetch_songs,
    parse_annotations,
    pool,
    run_benchmark,
    split_songs,
)
from app.stem_separation import SeparatedStems
from app.transcription import DrumEvent, DrumInstrument


def _event(time: float, instrument: DrumInstrument) -> DrumEvent:
    return DrumEvent(id=f"{instrument.value}-{time}", time=time, instrument=instrument)


class _FakeSeparator:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def separate(self, audio_path: Path, destination_dir: Path) -> SeparatedStems:
        self.calls.append(audio_path)
        destination_dir.mkdir(parents=True, exist_ok=True)
        drums = destination_dir / "drums.wav"
        accompaniment = destination_dir / "no_drums.wav"
        drums.write_bytes(b"drums of " + audio_path.name.encode())
        accompaniment.write_bytes(b"rest")
        return SeparatedStems(drums_path=drums, accompaniment_path=accompaniment)


class _FakeTranscriber:
    def __init__(self, events: list[DrumEvent]) -> None:
        self.events = events
        self.paths: list[Path] = []

    def transcribe(self, audio_path: Path) -> list[DrumEvent]:
        self.paths.append(audio_path)
        return self.events


def _fake_download(source: str, destination: Path) -> None:
    if source.endswith("_class.txt"):
        destination.write_text("0.5\tKD\n1.0\tSD\n")
    else:
        destination.write_bytes(b"audio")


def test_parse_annotations_maps_classes_and_skips_other_and_blank_lines():
    text = "0.010000 \t KD \n0.570000 \t SD \n\n0.6\tHH\n0.7\tTT\n0.8\tCY\n0.9\tOT\n"

    result = parse_annotations(text)

    assert result == [
        LabelledHit(0.01, "kick"),
        LabelledHit(0.57, "snare"),
        LabelledHit(0.6, "hihat"),
        LabelledHit(0.7, "toms"),
        LabelledHit(0.8, "cymbals"),
    ]


def test_groups_merge_open_and_closed_hihat_and_cover_every_instrument():
    covered = set().union(*GROUPS.values())

    assert GROUPS["hihat"] == {DrumInstrument.HIHAT_CLOSED, DrumInstrument.HIHAT_OPEN}
    assert covered == set(DrumInstrument)


def test_evaluate_song_scores_each_group_separately():
    events = [_event(0.5, DrumInstrument.KICK), _event(1.0, DrumInstrument.HIHAT_OPEN), _event(2.0, DrumInstrument.KICK)]
    hits = [LabelledHit(0.51, "kick"), LabelledHit(1.0, "hihat"), LabelledHit(1.5, "snare")]

    result = evaluate_song(events, hits)

    assert result["kick"] == MatchCounts.from_counts(1, 1, 0)
    assert result["hihat"] == MatchCounts.from_counts(1, 0, 0)
    assert result["snare"] == MatchCounts.from_counts(0, 0, 1)


def test_evaluate_song_does_not_match_a_hit_to_another_group():
    events = [_event(1.0, DrumInstrument.SNARE)]
    hits = [LabelledHit(1.0, "kick")]

    result = evaluate_song(events, hits)

    assert result["kick"] == MatchCounts.from_counts(0, 0, 1)
    assert result["snare"] == MatchCounts.from_counts(0, 1, 0)


def test_pool_sums_counts_instead_of_averaging_rates():
    song_a = {"kick": MatchCounts.from_counts(9, 1, 0)}
    song_b = {"kick": MatchCounts.from_counts(0, 0, 10)}

    result = pool([song_a, song_b])

    assert result["kick"] == MatchCounts.from_counts(9, 1, 10)


def test_split_songs_is_deterministic_disjoint_and_complete():
    tune, held_out = split_songs(MDB_SONGS)

    assert len(MDB_SONGS) == 23
    assert set(tune).isdisjoint(held_out)
    assert sorted(tune + held_out) == sorted(MDB_SONGS)
    assert split_songs(tuple(reversed(MDB_SONGS))) == (tune, held_out)


def test_fetch_songs_downloads_and_separates_each_missing_song(tmp_path):
    separator = _FakeSeparator()

    fetch_songs(("SongA", "SongB"), tmp_path, _fake_download, separator)

    song_dir = tmp_path / "SongA"
    assert (song_dir / "drums.wav").read_bytes() == b"drums of mix.wav"
    assert (song_dir / "drum_only.wav").exists()
    assert parse_annotations((song_dir / "annotations.txt").read_text()) == [
        LabelledHit(0.5, "kick"),
        LabelledHit(1.0, "snare"),
    ]
    assert len(separator.calls) == 2


def test_fetch_songs_skips_songs_already_present(tmp_path):
    separator = _FakeSeparator()
    fetch_songs(("SongA",), tmp_path, _fake_download, separator)

    fetch_songs(("SongA",), tmp_path, _fake_download, separator)

    assert len(separator.calls) == 1


@pytest.mark.parametrize(("condition", "file_name"), [("demucs", "drums.wav"), ("drum_only", "drum_only.wav")])
def test_run_benchmark_transcribes_the_audio_for_the_condition(tmp_path, condition, file_name):
    fetch_songs(("SongA",), tmp_path, _fake_download, _FakeSeparator())
    transcriber = _FakeTranscriber([_event(0.5, DrumInstrument.KICK)])

    run_benchmark(("SongA",), tmp_path, transcriber, condition, io.StringIO())

    assert transcriber.paths == [tmp_path / "SongA" / file_name]


def test_run_benchmark_prints_pooled_rows_and_skips_missing_songs(tmp_path):
    fetch_songs(("SongA",), tmp_path, _fake_download, _FakeSeparator())
    transcriber = _FakeTranscriber([_event(0.5, DrumInstrument.KICK), _event(3.0, DrumInstrument.KICK)])
    out = io.StringIO()

    exit_code = run_benchmark(("SongA", "SongB"), tmp_path, transcriber, "demucs", out)

    report = out.getvalue()
    assert exit_code == 0
    assert "SongB: missing" in report
    assert "kick" in report and "0.50  1.00  0.67" in report
