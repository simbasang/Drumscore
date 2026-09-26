import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from app.engine_process import detached_process_kwargs
from app.transcription import DrumEvent, DrumInstrument, TranscriptionError

_RUNNER_DIR = Path(__file__).resolve().parent.parent / "drumscript_runner"
_RUNNER_SCRIPT = _RUNNER_DIR / "run_transcription.py"
_TIMEOUT_SECONDS = 600

_INSTRUMENT_MAP = {
    "kick": DrumInstrument.KICK,
    "snare": DrumInstrument.SNARE,
    "hi_hat_closed": DrumInstrument.HIHAT_CLOSED,
    "hi_hat_open": DrumInstrument.HIHAT_OPEN,
    "crash": DrumInstrument.CRASH,
    "ride": DrumInstrument.RIDE,
    "low_tom": DrumInstrument.TOM_LOW,
    "mid_tom": DrumInstrument.TOM_MID,
    "high_tom": DrumInstrument.TOM_HIGH,
}


def runner_python() -> Path:
    if sys.platform == "win32":
        return _RUNNER_DIR / ".venv" / "Scripts" / "python.exe"
    return _RUNNER_DIR / ".venv" / "bin" / "python"


def _map_events(raw_events: list[dict]) -> list[DrumEvent]:
    events: list[DrumEvent] = []

    for raw_event in raw_events:
        time = raw_event["time_sec"]
        for raw_instrument in raw_event["instruments"]:
            instrument = _INSTRUMENT_MAP.get(raw_instrument)
            if instrument is None:
                continue
            events.append(
                DrumEvent(
                    id=str(uuid.uuid4()),
                    time=time,
                    instrument=instrument,
                    provenance="drumscript",
                )
            )

    return events


class DrumScriptTranscriber:
    def transcribe(self, audio_path: Path) -> list[DrumEvent]:
        runner = runner_python()

        if not runner.exists():
            raise TranscriptionError(
                f"DrumScript runner environment not found at {runner}. "
                "Run `uv sync` inside backend/drumscript_runner first."
            )

        with tempfile.TemporaryDirectory() as scratch_dir:
            events_path = Path(scratch_dir) / "events.json"
            drumscript_output_dir = Path(scratch_dir) / "drumscript_output"

            try:
                result = subprocess.run(
                    [str(runner), str(_RUNNER_SCRIPT), str(audio_path), str(events_path), str(drumscript_output_dir)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=_TIMEOUT_SECONDS,
                    **detached_process_kwargs(),
                )
            except subprocess.TimeoutExpired as error:
                raise TranscriptionError(
                    f"Drum transcription timed out after {_TIMEOUT_SECONDS} seconds"
                ) from error

            if result.returncode != 0:
                raise TranscriptionError(f"Drum transcription failed: {result.stderr.strip()}")

            try:
                payload = json.loads(events_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise TranscriptionError("Drum transcription returned invalid output") from error

        return _map_events(payload.get("events", []))
