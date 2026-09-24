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


def mock_ydl(mock_ydl_cls, info):
    ydl = mock_ydl_cls.return_value.__enter__.return_value
    ydl.extract_info.return_value = info
    return ydl


def test_build_ydl_options_targets_wav_output_in_destination_dir(tmp_path):
    options = _build_ydl_options(tmp_path)

    assert options["outtmpl"] == str(tmp_path / "source.%(ext)s")
    assert options["postprocessors"][0]["preferredcodec"] == "wav"
    assert options["postprocessor_args"]["extractaudio"] == ["-ar", "44100", "-ac", "2"]


def test_build_ydl_options_sets_a_socket_timeout(tmp_path):
    options = _build_ydl_options(tmp_path)

    assert options["socket_timeout"] == 30


def test_build_ydl_options_caps_the_download_size(tmp_path):
    options = _build_ydl_options(tmp_path, max_download_bytes=1234)

    assert options["max_filesize"] == 1234


def test_extract_raises_when_no_output_file_is_produced(tmp_path, source):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl(mock_ydl_cls, {"title": "Song", "duration": 200})

        with pytest.raises(AudioExtractionError, match="did not produce an output file .*200 MB limit"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")


def test_extract_reads_metadata_first_then_downloads(tmp_path, source):
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"fake wav data")
    info = {"title": "Never Gonna Give You Up", "duration": 213}

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, info)

        result = YtDlpAudioExtractor().extract(source, destination_dir)

    assert result.audio_path == destination_dir / "source.wav"
    assert result.title == "Never Gonna Give You Up"
    ydl.extract_info.assert_called_once_with(source.url, download=False)
    ydl.process_ie_result.assert_called_once_with(info, download=True)


def test_extract_fails_when_metadata_is_missing(tmp_path, source):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, None)

        with pytest.raises(AudioExtractionError, match="Could not read the source's metadata"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")

    ydl.process_ie_result.assert_not_called()


def test_too_long_source_is_rejected_before_download(tmp_path, source):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, {"title": "Mix", "duration": 3725})

        with pytest.raises(AudioExtractionError, match=r"Source is 62:05 long; the limit is 15:00"):
            YtDlpAudioExtractor(max_duration_seconds=900).extract(source, tmp_path / "job-1")

    ydl.process_ie_result.assert_not_called()


def test_source_at_the_duration_limit_is_accepted(tmp_path, source):
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"x")

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl(mock_ydl_cls, {"title": "Song", "duration": 900})

        result = YtDlpAudioExtractor(max_duration_seconds=900).extract(source, destination_dir)

    assert result.audio_path.exists()


def test_unknown_duration_is_allowed(tmp_path, source):
    destination_dir = tmp_path / "job-1"
    destination_dir.mkdir()
    (destination_dir / "source.wav").write_bytes(b"x")

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, {"title": "Song"})

        YtDlpAudioExtractor().extract(source, destination_dir)

    ydl.process_ie_result.assert_called_once()


@pytest.mark.parametrize("info", [{"is_live": True}, {"live_status": "is_live"}, {"live_status": "is_upcoming"}])
def test_live_streams_are_rejected(tmp_path, source, info):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl(mock_ydl_cls, {"title": "Live", **info})

        with pytest.raises(AudioExtractionError, match="Live streams are not supported"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")


@pytest.mark.parametrize("size_key", ["filesize", "filesize_approx"])
def test_too_large_source_is_rejected_before_download(tmp_path, source, size_key):
    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        ydl = mock_ydl(mock_ydl_cls, {"title": "Big", "duration": 100, size_key: 300 * 1024**2})

        with pytest.raises(AudioExtractionError, match="Source audio is 300 MB; the limit is 200 MB"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")

    ydl.process_ie_result.assert_not_called()


def test_extract_wraps_download_errors(tmp_path, source):
    import yt_dlp

    with patch("app.youtube_audio_extractor.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value.extract_info.side_effect = (
            yt_dlp.utils.DownloadError("video unavailable")
        )

        with pytest.raises(AudioExtractionError, match="video unavailable"):
            YtDlpAudioExtractor().extract(source, tmp_path / "job-1")
