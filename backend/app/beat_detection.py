from pathlib import Path
from typing import Protocol

from app.timing import BeatPoint


class BeatDetectionError(Exception):
    pass


class BeatDetector(Protocol):
    def detect(self, drums_path: Path, accompaniment_path: Path) -> list[BeatPoint]: ...
