from pathlib import Path
from typing import Protocol

from app.timing import BeatPoint


class BeatDetectionError(Exception):
    pass


class BeatDetector(Protocol):
    def detect(self, audio_path: Path) -> list[BeatPoint]: ...
