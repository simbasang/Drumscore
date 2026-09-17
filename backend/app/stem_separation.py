from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class StemSeparationError(Exception):
    pass


@dataclass(frozen=True)
class SeparatedStems:
    drums_path: Path
    accompaniment_path: Path


class StemSeparator(Protocol):
    def separate(self, audio_path: Path, destination_dir: Path) -> SeparatedStems: ...
