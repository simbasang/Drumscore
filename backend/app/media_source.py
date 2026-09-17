from dataclasses import dataclass
from typing import Protocol


class InvalidSourceUrlError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSource:
    url: str
    provider: str
    external_id: str


class MediaSourceValidator(Protocol):
    def parse(self, url: str) -> ParsedSource: ...
