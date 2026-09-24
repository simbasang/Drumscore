from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.media_source import ParsedSource


class AudioExtractionError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedAudio:
    audio_path: Path
    # Human-readable source title (e.g. the YouTube video title) when the
    # provider reports one; used as the project's display title.
    title: str | None = None


class AudioExtractor(Protocol):
    def extract(self, source: ParsedSource, destination_dir: Path) -> ExtractedAudio: ...
