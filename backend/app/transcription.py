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
    confidence: float | None = None


class DrumTranscriber(Protocol):
    def transcribe(self, audio_path: Path) -> list[DrumEvent]: ...
