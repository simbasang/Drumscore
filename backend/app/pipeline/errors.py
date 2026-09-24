from app.audio_extraction import AudioExtractionError
from app.beat_detection import BeatDetectionError
from app.media_source import InvalidSourceUrlError
from app.stem_separation import StemSeparationError
from app.tempo_estimation import TempoEstimationError
from app.transcription import TranscriptionError


class InsufficientBeatsError(Exception):
    pass


# Expected, input-determined failures: retrying the same input cannot
# succeed, so the job fails immediately with the engine's message. Any
# other exception is treated as transient and retried with backoff.
PERMANENT_ERRORS: tuple[type[Exception], ...] = (
    AudioExtractionError,
    StemSeparationError,
    TranscriptionError,
    TempoEstimationError,
    BeatDetectionError,
    InsufficientBeatsError,
    InvalidSourceUrlError,
)


def is_permanent(error: BaseException) -> bool:
    return isinstance(error, PERMANENT_ERRORS)


def backoff_seconds(attempts: int, base_seconds: int) -> int:
    return base_seconds * 2 ** max(attempts - 1, 0)
