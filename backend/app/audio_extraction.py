from pathlib import Path
from typing import Protocol

from app.media_source import ParsedSource


class AudioExtractionError(Exception):
    pass


class AudioExtractor(Protocol):
    def extract(self, source: ParsedSource, destination_dir: Path) -> Path: ...
