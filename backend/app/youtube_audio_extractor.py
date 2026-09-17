from pathlib import Path

import yt_dlp

from app.audio_extraction import AudioExtractionError
from app.media_source import ParsedSource

_TARGET_SAMPLE_RATE = "44100"
_TARGET_CHANNELS = "2"
_SOCKET_TIMEOUT_SECONDS = 30


def _build_ydl_options(destination_dir: Path) -> dict:
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
    }


class YtDlpAudioExtractor:
    def extract(self, source: ParsedSource, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        options = _build_ydl_options(destination_dir)

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([source.url])
        except yt_dlp.utils.DownloadError as error:
            raise AudioExtractionError(f"Failed to download audio: {error}") from error

        output_path = destination_dir / "source.wav"
        if not output_path.exists():
            raise AudioExtractionError("Audio extraction did not produce an output file")

        return output_path
