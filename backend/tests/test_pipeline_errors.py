import pytest

from app.audio_extraction import AudioExtractionError
from app.beat_detection import BeatDetectionError
from app.media_source import InvalidSourceUrlError
from app.pipeline.errors import InsufficientBeatsError, backoff_seconds, is_permanent
from app.stem_separation import StemSeparationError
from app.tempo_estimation import TempoEstimationError
from app.transcription import TranscriptionError


@pytest.mark.parametrize(
    "error",
    [
        AudioExtractionError("video unavailable"),
        StemSeparationError("demucs failed"),
        TranscriptionError("model crashed"),
        TempoEstimationError("no tempo"),
        BeatDetectionError("no onsets"),
        InsufficientBeatsError("1 beat"),
        InvalidSourceUrlError("bad url"),
    ],
)
def test_domain_errors_are_permanent(error):
    assert is_permanent(error) is True


@pytest.mark.parametrize("error", [RuntimeError("oom"), OSError("disk"), KeyError("x")])
def test_unexpected_errors_are_retryable(error):
    assert is_permanent(error) is False


@pytest.mark.parametrize("attempts, expected", [(0, 30), (1, 30), (2, 60), (3, 120)])
def test_backoff_doubles_per_attempt(attempts, expected):
    assert backoff_seconds(attempts, 30) == expected
