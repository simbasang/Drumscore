import re
from urllib.parse import parse_qs, urlparse

from app.media_source import InvalidSourceUrlError, ParsedSource

_VIDEO_ID_PATTERN = re.compile(r"^[\w-]{11}$")
_LONG_FORM_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_SHORT_FORM_HOST = "youtu.be"


class YouTubeSourceValidator:
    def parse(self, url: str) -> ParsedSource:
        video_id = self._extract_video_id(url.strip())

        if video_id is None:
            raise InvalidSourceUrlError(f"'{url}' is not a supported YouTube URL")

        return ParsedSource(url=url, provider="youtube", external_id=video_id)

    def _extract_video_id(self, url: str) -> str | None:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return None

        host = parsed.netloc.lower()

        if host == _SHORT_FORM_HOST:
            candidate = parsed.path.lstrip("/")
        elif host in _LONG_FORM_HOSTS:
            if parsed.path == "/watch":
                candidate = parse_qs(parsed.query).get("v", [None])[0]
            elif parsed.path.startswith("/shorts/"):
                candidate = parsed.path.removeprefix("/shorts/")
            else:
                return None
        else:
            return None

        if candidate and _VIDEO_ID_PATTERN.match(candidate):
            return candidate

        return None
