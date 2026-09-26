import importlib.util
import json
import sys
import types
from unittest.mock import MagicMock

import pytest

from app.drumscript_transcriber import _RUNNER_SCRIPT


def load_runner(monkeypatch, transcribe):
    monkeypatch.setitem(sys.modules, "drumscript", types.SimpleNamespace(transcribe=transcribe))
    spec = importlib.util.spec_from_file_location("run_transcription", _RUNNER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_writes_drumscript_output_to_the_given_directory(monkeypatch, tmp_path):
    transcribe = MagicMock(return_value={"events": [{"time_sec": 1.0, "instruments": ["kick"], "extra": 1}]})
    runner = load_runner(monkeypatch, transcribe)
    audio, events, output_dir = tmp_path / "stems" / "drums.wav", tmp_path / "events.json", tmp_path / "scratch" / "out"
    monkeypatch.setattr(sys, "argv", ["run_transcription.py", str(audio), str(events), str(output_dir)])

    runner.main()

    assert transcribe.call_args.kwargs["output_dir"] == str(output_dir)
    assert json.loads(events.read_text()) == {"events": [{"time_sec": 1.0, "instruments": ["kick"]}]}


def test_main_exits_with_usage_on_wrong_argument_count(monkeypatch, capsys):
    runner = load_runner(monkeypatch, MagicMock())
    monkeypatch.setattr(sys, "argv", ["run_transcription.py", "drums.wav", "events.json"])

    with pytest.raises(SystemExit) as exit_info:
        runner.main()

    assert exit_info.value.code == 2
    assert "<drumscript_output_dir>" in capsys.readouterr().err
