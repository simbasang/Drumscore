import subprocess
import sys
from pathlib import Path

from app.stem_separation import SeparatedStems, StemSeparationError

_MODEL_NAME = "htdemucs"


class DemucsStemSeparator:
    def separate(self, audio_path: Path, destination_dir: Path) -> SeparatedStems:
        destination_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "demucs",
                "--two-stems",
                "drums",
                "-n",
                _MODEL_NAME,
                "-o",
                str(destination_dir),
                str(audio_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise StemSeparationError(f"Demucs failed: {result.stderr.strip()}")

        output_dir = destination_dir / _MODEL_NAME / audio_path.stem
        drums_path = output_dir / "drums.wav"
        accompaniment_path = output_dir / "no_drums.wav"

        if not drums_path.exists() or not accompaniment_path.exists():
            raise StemSeparationError("Demucs did not produce the expected output files")

        return SeparatedStems(drums_path=drums_path, accompaniment_path=accompaniment_path)
