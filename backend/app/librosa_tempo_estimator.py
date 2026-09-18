from pathlib import Path

import librosa
import numpy as np

from app.tempo_estimation import TempoEstimationError


class LibrosaTempoEstimator:
    def estimate(self, audio_path: Path) -> float:
        try:
            y, sr = librosa.load(str(audio_path), sr=None, mono=True)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        except Exception as error:
            raise TempoEstimationError(f"Failed to estimate tempo: {error}") from error

        return float(np.asarray(tempo).reshape(-1)[0])
