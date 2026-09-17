from unittest.mock import patch

import pytest

from app.audio_extraction import AudioExtractionError
from app.media_source import ParsedSource
from app.youtube_audio_extractor import YtDlpAudioExtractor, _build_ydl_options


@pytest.fixture
def source():
    return ParsedSource(
        url="https://youtu.be/dQw4w9WgXcQ", provider="youtube", external_id="dQw4w9WgXcQ"
    )


def test_build_ydl_options_targets_wav_output_in_destination_dir(tmp_path):
    options = _build_ydl_options(tmp_path)

    assert options["outtmpl"] == str(tmp_path / "source.%(ext)s")
    assert options["postprocessors"][0]["preferredcodec"] == "wav"
    assert options["postprocessor_args"]["extractaudio"] == ["-ar", "44100", "-ac", "2"]


def test_extract_raises_when_no_output_file_is_produced(tmp_path, source):
    extractor = YtDlpAudioExtractor()

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.download.return_value = None

        with pytest.raises(AudioExtractionError, match="did not produce"):
            extractor.extract(source, tmp_path / "job-1")


def test_extract_returns_output_path_when_file_exists(tmp_path, source):
    extractor = YtDlpAudioExtractor()
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"fake wav data")

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.download.return_value = None

        result = extractor.extract(source, destination_dir)

    assert result == destination_dir / "source.wav"


def test_extract_wraps_download_errors(tmp_path, source):
    import yt_dlp

    extractor = YtDlpAudioExtractor()

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.download.side_effect = (
            yt_dlp.utils.DownloadError("video unavailable")
        )

        with pytest.raises(AudioExtractionError, match="video unavailable"):
            extractor.extract(source, tmp_path / "job-1")
