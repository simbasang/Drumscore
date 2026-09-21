import dataclasses
from pathlib import Path
from typing import Protocol


class TempoEstimationError(Exception):
    pass


class TempoEstimator(Protocol):
    def estimate(self, audio_path: Path) -> float: ...


@dataclasses.dataclass(frozen=True)
class TempoCandidate:
    bpm: float
    phase_error: float


@dataclasses.dataclass(frozen=True)
class TempoEstimate:
    bpm: float
    candidates: tuple[TempoCandidate, ...]
