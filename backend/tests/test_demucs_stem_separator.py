import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.demucs_stem_separator import DemucsStemSeparator
from app.engine_process import detached_process_kwargs
from app.stem_separation import StemSeparationError


def _make_completed_process(returncode: int, stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stderr = stderr
    return result


def test_separate_invokes_demucs_with_two_stems_drums_flag(tmp_path):
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake audio")
    destination_dir = tmp_path / "out"
    output_dir = destination_dir / "htdemucs" / "source"
    output_dir.mkdir(parents=True)
    (output_dir / "drums.wav").write_bytes(b"drums")
    (output_dir / "no_drums.wav").write_bytes(b"no drums")

    with patch("app.demucs_stem_separator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(returncode=0)

        DemucsStemSeparator().separate(audio_path, destination_dir)

        mock_run.assert_called_once_with(
            [
                sys.executable,
                "-m",
                "demucs",
                "--two-stems",
                "drums",
                "-n",
                "htdemucs",
                "-o",
                str(destination_dir),
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            **detached_process_kwargs(),
        )


def test_separate_raises_when_demucs_times_out(tmp_path):
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake audio")

    with patch("app.demucs_stem_separator.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="demucs", timeout=600)

        with pytest.raises(StemSeparationError, match="timed out"):
            DemucsStemSeparator().separate(audio_path, tmp_path / "out")


def test_separate_returns_drum_and_accompaniment_paths(tmp_path):
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake audio")
    destination_dir = tmp_path / "out"
    output_dir = destination_dir / "htdemucs" / "source"
    output_dir.mkdir(parents=True)
    (output_dir / "drums.wav").write_bytes(b"drums")
    (output_dir / "no_drums.wav").write_bytes(b"no drums")

    with patch("app.demucs_stem_separator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(returncode=0)

        result = DemucsStemSeparator().separate(audio_path, destination_dir)

    assert result.drums_path == output_dir / "drums.wav"
    assert result.accompaniment_path == output_dir / "no_drums.wav"


def test_separate_raises_when_demucs_command_fails(tmp_path):
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake audio")

    with patch("app.demucs_stem_separator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(returncode=1, stderr="out of memory")

        with pytest.raises(StemSeparationError, match="out of memory"):
            DemucsStemSeparator().separate(audio_path, tmp_path / "out")


def test_separate_raises_when_expected_output_files_are_missing(tmp_path):
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake audio")

    with patch("app.demucs_stem_separator.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(returncode=0)

        with pytest.raises(StemSeparationError, match="did not produce"):
            DemucsStemSeparator().separate(audio_path, tmp_path / "out")


_FAILING_ENGINE = "import sys; sys.stderr.buffer.write(b'boom \\x8d\\x81 end'); sys.exit(1)"


def test_failure_message_survives_undecodable_stderr_bytes(tmp_path):
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake audio")
    real_run = subprocess.run

    def run_failing_engine(command, **kwargs):
        return real_run([sys.executable, "-c", _FAILING_ENGINE], **kwargs)

    with patch("app.demucs_stem_separator.subprocess.run", side_effect=run_failing_engine):
        with pytest.raises(StemSeparationError, match="Demucs failed: boom .* end"):
            DemucsStemSeparator().separate(audio_path, tmp_path / "out")
