import uuid
from pathlib import Path

from app.kick_detection import KickDetector
from app.transcription import DrumEvent, DrumInstrument, DrumTranscriber

KICK_DETECTOR_PROVENANCE = "kick_detector"


class KickReplacingTranscriber:
    """Takes every kick from the kick detector and everything else from the
    base engine, unchanged. The base engine's own kicks are dropped: on
    held-out real songs they are too imprecise to keep, even merged with the
    detector's (docs/kick-detection-evaluation.md). The engine's full,
    unmodified output stays available through transcribe_with_engine_output.
    Added kicks carry no confidence: the detector's flux strength is not a
    calibrated probability."""

    def __init__(self, base: DrumTranscriber, detector: KickDetector) -> None:
        self.base = base
        self.detector = detector

    def transcribe(self, audio_path: Path) -> list[DrumEvent]:
        events, _ = self.transcribe_with_engine_output(audio_path)
        return events

    def transcribe_with_engine_output(self, audio_path: Path) -> tuple[list[DrumEvent], list[DrumEvent]]:
        engine_events = self.base.transcribe(audio_path)
        kicks = [
            DrumEvent(
                id=str(uuid.uuid4()),
                time=time,
                instrument=DrumInstrument.KICK,
                provenance=KICK_DETECTOR_PROVENANCE,
            )
            for time in self.detector.detect(audio_path)
        ]
        others = [event for event in engine_events if event.instrument != DrumInstrument.KICK]
        return sorted([*others, *kicks], key=lambda event: event.time), engine_events
