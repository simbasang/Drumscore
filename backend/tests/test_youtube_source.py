import pytest

from app.media_source import InvalidSourceUrlError
from app.youtube_source import YouTubeSourceValidator

validator = YouTubeSourceValidator()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ&t=10s",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    ],
)
def test_parse_extracts_video_id_from_supported_url_formats(url):
    result = validator.parse(url)

    assert result.external_id == "dQw4w9WgXcQ"
    assert result.provider == "youtube"
    assert result.url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://vimeo.com/12345",
        "not a url",
        "https://www.youtube.com/watch?v=short",
        "ftp://youtu.be/dQw4w9WgXcQ",
        "",
    ],
)
def test_parse_rejects_unsupported_or_malformed_urls(url):
    with pytest.raises(InvalidSourceUrlError):
        validator.parse(url)
