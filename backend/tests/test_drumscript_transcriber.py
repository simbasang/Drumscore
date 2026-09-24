import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.drumscript_transcriber import _RUNNER_SCRIPT, DrumScriptTranscriber, runner_python
from app.engine_process import detached_process_kwargs
from app.transcription import DrumInstrument, TranscriptionError


def _make_completed_process(returncode: int, stderr: str = ""):
    result = type("Result", (), {})()
    result.returncode = returncode
    result.stdout = ""
    result.stderr = stderr
    return result


def _writes_events_file(events: list[dict]):
    def side_effect(command, **kwargs):
        Path(command[-1]).write_text(json.dumps({"events": events}))
        return _make_completed_process(returncode=0)

    return side_effect


@pytest.fixture(autouse=True)
def fake_runner_python(tmp_path):
    runner_python = tmp_path / "python.exe"
    runner_python.write_text("")
    with patch("app.drumscript_transcriber.runner_python", return_value=runner_python):
        yield runner_python


def test_transcribe_maps_known_instruments_and_splits_simultaneous_hits(tmp_path):
    events = [
        {"time_sec": 1.5, "instruments": ["kick", "hi_hat_closed"]},
        {"time_sec": 2.0, "instruments": ["snare"]},
    ]

    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.side_effect = _writes_events_file(events)

        events_result = DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")

    assert len(events_result) == 3
    assert {(e.time, e.instrument) for e in events_result} == {
        (1.5, DrumInstrument.KICK),
        (1.5, DrumInstrument.HIHAT_CLOSED),
        (2.0, DrumInstrument.SNARE),
    }
    assert all(e.id for e in events_result)


def test_transcribe_filters_out_unknown_instrument(tmp_path):
    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.side_effect = _writes_events_file(
            [{"time_sec": 1.0, "instruments": ["unknown"]}]
        )

        events = DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")

    assert events == []


def test_transcribe_invokes_runner_script_with_audio_and_output_paths(tmp_path, fake_runner_python):
    audio_path = tmp_path / "drums.wav"

    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.side_effect = _writes_events_file([])

        DrumScriptTranscriber().transcribe(audio_path)

        args, kwargs = mock_run.call_args
        command = args[0]
        assert command[0] == str(fake_runner_python)
        assert command[1] == str(_RUNNER_SCRIPT)
        assert command[2] == str(audio_path)
        assert kwargs["timeout"] == 600
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert detached_process_kwargs().items() <= kwargs.items()


def test_transcribe_raises_when_runner_exits_nonzero(tmp_path):
    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(returncode=1, stderr="boom")

        with pytest.raises(TranscriptionError, match="boom"):
            DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")


def test_transcribe_raises_when_output_file_is_missing(tmp_path):
    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed_process(returncode=0)

        with pytest.raises(TranscriptionError, match="invalid output"):
            DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")


def test_transcribe_raises_on_invalid_json_in_output_file(tmp_path):
    def side_effect(command, **kwargs):
        Path(command[-1]).write_text("not json")
        return _make_completed_process(returncode=0)

    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.side_effect = side_effect

        with pytest.raises(TranscriptionError, match="invalid output"):
            DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")


def test_transcribe_raises_on_timeout(tmp_path):
    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="run_transcription.py", timeout=600)

        with pytest.raises(TranscriptionError, match="timed out"):
            DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")


def test_runner_python_uses_unix_venv_layout_on_non_windows(monkeypatch):
    monkeypatch.setattr("app.drumscript_transcriber.sys.platform", "linux")

    result = runner_python()

    assert result.parts[-3:] == (".venv", "bin", "python")


def test_runner_python_uses_windows_venv_layout_on_windows(monkeypatch):
    monkeypatch.setattr("app.drumscript_transcriber.sys.platform", "win32")

    result = runner_python()

    assert result.parts[-3:] == (".venv", "Scripts", "python.exe")


def test_transcribe_raises_when_runner_environment_missing(tmp_path):
    missing_python = tmp_path / "does-not-exist" / "python.exe"

    with patch("app.drumscript_transcriber.runner_python", return_value=missing_python):
        with pytest.raises(TranscriptionError, match="runner environment"):
            DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")


def test_transcribe_sets_drumscript_as_provenance_and_leaves_confidence_null(tmp_path):
    with patch("app.drumscript_transcriber.subprocess.run") as mock_run:
        mock_run.side_effect = _writes_events_file(
            [{"time_sec": 1.0, "instruments": ["kick", "snare"]}]
        )

        events = DrumScriptTranscriber().transcribe(tmp_path / "drums.wav")

    assert len(events) == 2
    assert all(e.provenance == "drumscript" for e in events)
    assert all(e.confidence is None for e in events)


_FAILING_ENGINE = "import sys; sys.stderr.buffer.write(b'boom \\x8d\\x81 end'); sys.exit(1)"


def test_failure_message_survives_undecodable_stderr_bytes(tmp_path, fake_runner_python):
    audio_path = tmp_path / "drums.wav"
    audio_path.write_bytes(b"fake audio")
    real_run = subprocess.run

    def run_failing_engine(command, **kwargs):
        return real_run([sys.executable, "-c", _FAILING_ENGINE], **kwargs)

    with patch("app.drumscript_transcriber.subprocess.run", side_effect=run_failing_engine):
        with pytest.raises(TranscriptionError, match="Drum transcription failed: boom .* end"):
            DrumScriptTranscriber().transcribe(audio_path)
