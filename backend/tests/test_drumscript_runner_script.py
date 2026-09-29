import importlib.util
import json
import sys
import types
from unittest.mock import MagicMock

import pytest

from app.drumscript_transcriber import _RUNNER_SCRIPT

SAMPLE_RATE = 44100
LOADED_AUDIO = object()
NORMALISED_AUDIO = object()


def fake_drumscript(onsets, classified_events):
    return types.SimpleNamespace(
        SAMPLE_RATE=SAMPLE_RATE,
        load_audio=MagicMock(return_value=(LOADED_AUDIO, SAMPLE_RATE)),
        normalise_audio=MagicMock(return_value=NORMALISED_AUDIO),
        detect_onsets=MagicMock(return_value=onsets),
        classify_events=MagicMock(return_value=classified_events),
    )


def load_runner(monkeypatch, drumscript):
    monkeypatch.setitem(sys.modules, "drumscript", drumscript)
    spec = importlib.util.spec_from_file_location("run_transcription", _RUNNER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_runner(monkeypatch, tmp_path, drumscript):
    runner = load_runner(monkeypatch, drumscript)
    audio, events = tmp_path / "stems" / "drums.wav", tmp_path / "events.json"
    monkeypatch.setattr(sys, "argv", ["run_transcription.py", str(audio), str(events)])
    runner.main()
    return audio, json.loads(events.read_text())


def test_main_writes_detected_onset_times_unquantized(monkeypatch, tmp_path):
    drumscript = fake_drumscript(
        [0.2371, 0.5012],
        [
            {"time_sec": 0.2371, "instruments": ["snare"], "debug_features": {"centroid": 1}},
            {"time_sec": 0.5012, "instruments": ["hi_hat_closed", "kick"], "debug_features": {}},
        ],
    )

    _, output = run_runner(monkeypatch, tmp_path, drumscript)

    assert output == {
        "events": [
            {"time_sec": 0.2371, "instruments": ["snare"]},
            {"time_sec": 0.5012, "instruments": ["hi_hat_closed", "kick"]},
        ]
    }


def test_main_classifies_the_normalised_audio_at_drumscript_sample_rate(monkeypatch, tmp_path):
    drumscript = fake_drumscript([0.25], [{"time_sec": 0.25, "instruments": ["snare"], "debug_features": {}}])

    audio, _ = run_runner(monkeypatch, tmp_path, drumscript)

    drumscript.load_audio.assert_called_once_with(str(audio), sr=SAMPLE_RATE)
    drumscript.normalise_audio.assert_called_once_with(LOADED_AUDIO)
    drumscript.detect_onsets.assert_called_once_with(NORMALISED_AUDIO, SAMPLE_RATE)
    drumscript.classify_events.assert_called_once_with(NORMALISED_AUDIO, SAMPLE_RATE, [0.25])


def test_main_writes_no_events_for_silent_audio(monkeypatch, tmp_path):
    drumscript = fake_drumscript([], [])

    _, output = run_runner(monkeypatch, tmp_path, drumscript)

    assert output == {"events": []}


def test_main_exits_with_usage_on_wrong_argument_count(monkeypatch, capsys):
    runner = load_runner(monkeypatch, fake_drumscript([], []))
    monkeypatch.setattr(sys, "argv", ["run_transcription.py", "drums.wav"])

    with pytest.raises(SystemExit) as exit_info:
        runner.main()

    assert exit_info.value.code == 2
    assert "<output_json_path>" in capsys.readouterr().err
