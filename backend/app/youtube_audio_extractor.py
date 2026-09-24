from pathlib import Path

import yt_dlp

from app.audio_extraction import AudioExtractionError, ExtractedAudio
from app.media_source import ParsedSource

_TARGET_SAMPLE_RATE = "44100"
_TARGET_CHANNELS = "2"
_SOCKET_TIMEOUT_SECONDS = 30
_DEFAULT_MAX_DURATION_SECONDS = 900
_DEFAULT_MAX_DOWNLOAD_BYTES = 200 * 1024**2
_LIVE_STATUSES = {"is_live", "is_upcoming"}


def _build_ydl_options(destination_dir: Path, max_download_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES) -> dict:
    return {
        "format": "bestaudio/best",
        "outtmpl": str(destination_dir / "source.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav"},
        ],
        "postprocessor_args": {
            "extractaudio": ["-ar", _TARGET_SAMPLE_RATE, "-ac", _TARGET_CHANNELS],
        },
        "quiet": True,
        "noplaylist": True,
        "noprogress": True,
        "socket_timeout": _SOCKET_TIMEOUT_SECONDS,
        # Backstop for sources whose metadata has no size: yt-dlp skips
        # (does not raise on) a download that grows past this.
        "max_filesize": max_download_bytes,
    }


def _minutes(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _megabytes(size: float) -> str:
    return f"{size / 1024**2:.0f}"


class YtDlpAudioExtractor:
    """Reads the source's metadata first and refuses live streams, sources
    longer than `max_duration_seconds` and audio larger than
    `max_download_bytes` before downloading anything."""

    def __init__(
        self,
        max_duration_seconds: int = _DEFAULT_MAX_DURATION_SECONDS,
        max_download_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self.max_duration_seconds = max_duration_seconds
        self.max_download_bytes = max_download_bytes

    def extract(self, source: ParsedSource, destination_dir: Path) -> ExtractedAudio:
        destination_dir.mkdir(parents=True, exist_ok=True)
        options = _build_ydl_options(destination_dir, self.max_download_bytes)

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source.url, download=False)
                if not isinstance(info, dict):
                    raise AudioExtractionError("Could not read the source's metadata")
                self._check_limits(info)
                ydl.process_ie_result(info, download=True)
        except yt_dlp.utils.DownloadError as error:
            raise AudioExtractionError(f"Failed to download audio: {error}") from error

        output_path = destination_dir / "source.wav"
        if not output_path.exists():
            raise AudioExtractionError(
                "Audio extraction did not produce an output file "
                f"(the download may exceed the {_megabytes(self.max_download_bytes)} MB limit)"
            )

        return ExtractedAudio(audio_path=output_path, title=info.get("title"))

    def _check_limits(self, info: dict) -> None:
        if info.get("is_live") or info.get("live_status") in _LIVE_STATUSES:
            raise AudioExtractionError("Live streams are not supported")
        duration = info.get("duration")
        if isinstance(duration, int | float) and duration > self.max_duration_seconds:
            raise AudioExtractionError(
                f"Source is {_minutes(duration)} long; the limit is {_minutes(self.max_duration_seconds)}"
            )
        size = info.get("filesize") or info.get("filesize_approx")
        if isinstance(size, int | float) and size > self.max_download_bytes:
            raise AudioExtractionError(
                f"Source audio is {_megabytes(size)} MB; the limit is {_megabytes(self.max_download_bytes)} MB"
            )
