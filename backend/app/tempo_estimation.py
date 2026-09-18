from pathlib import Path
from typing import Protocol


class TempoEstimationError(Exception):
    pass


class TempoEstimator(Protocol):
    def estimate(self, audio_path: Path) -> float: ...
