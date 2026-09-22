from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class TranscriptionError(Exception):
    pass


class DrumInstrument(str, Enum):
    KICK = "kick"
    SNARE = "snare"
    HIHAT_CLOSED = "hihat_closed"
    HIHAT_OPEN = "hihat_open"
    CRASH = "crash"
    RIDE = "ride"
    TOM_LOW = "tom_low"
    TOM_MID = "tom_mid"
    TOM_HIGH = "tom_high"


@dataclass(frozen=True)
class DrumEvent:
    id: str
    time: float
    instrument: DrumInstrument
    velocity: float | None = None
    # Confidence in this event's instrument classification, in [0, 1], or
    # None when the producing engine has no defensible confidence signal.
    # DrumScript (this v1.0's only transcriber) is a deterministic
    # rule-based physics/threshold classifier - see
    # backend/drumscript_runner/.venv/.../drum_classifier/classify.py,
    # which assigns instruments via hard-coded frequency/energy-ratio
    # thresholds with no probability or score-margin output anywhere in
    # its classification path - so DrumScriptTranscriber always leaves this
    # None. Never synthesize a confidence value (e.g. from a
    # threshold-distance heuristic) merely to populate this field; null is
    # the honest answer until an engine with a real signal is integrated.
    confidence: float | None = None
    # Which engine/stage produced this event, e.g. "drumscript". None for
    # events not yet attributed to a producing engine.
    provenance: str | None = None
    measure: int | None = None
    beat: int | None = None
    subdivision: int | None = None


class DrumTranscriber(Protocol):
    def transcribe(self, audio_path: Path) -> list[DrumEvent]: ...
