from pathlib import Path

import numpy as np
import soundfile as sf


def mix_stems(drums_path: Path, accompaniment_path: Path, destination: Path) -> Path:
    """Rebuilds the full mix as drums + accompaniment. Demucs splits the
    source into exactly these two stems, so their sum stands in for the
    source audio, which may already have been pruned by the time the
    tempo stage runs. Written as float WAV, so the sum never clips."""
    drums, drums_rate = sf.read(str(drums_path), dtype="float32", always_2d=True)
    accompaniment, accompaniment_rate = sf.read(str(accompaniment_path), dtype="float32", always_2d=True)
    if drums_rate != accompaniment_rate:
        raise ValueError(f"Cannot mix stems: sample rates differ ({drums_rate} Hz vs {accompaniment_rate} Hz)")

    length = max(len(drums), len(accompaniment))
    channels = max(drums.shape[1], accompaniment.shape[1])
    mix = np.zeros((length, channels), dtype=np.float32)
    mix[: len(drums)] += drums
    mix[: len(accompaniment)] += accompaniment

    sf.write(str(destination), mix, drums_rate, subtype="FLOAT")
    return destination
