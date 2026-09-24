import subprocess
import sys
from pathlib import Path

from app.engine_process import detached_process_kwargs
from app.stem_separation import SeparatedStems, StemSeparationError

_MODEL_NAME = "htdemucs"
_TIMEOUT_SECONDS = 600


class DemucsStemSeparator:
    def separate(self, audio_path: Path, destination_dir: Path) -> SeparatedStems:
        destination_dir.mkdir(parents=True, exist_ok=True)

        try:
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
                timeout=_TIMEOUT_SECONDS,
                **detached_process_kwargs(),
            )
        except subprocess.TimeoutExpired as error:
            raise StemSeparationError(
                f"Demucs timed out after {_TIMEOUT_SECONDS} seconds"
            ) from error

        if result.returncode != 0:
            raise StemSeparationError(f"Demucs failed: {result.stderr.strip()}")

        output_dir = destination_dir / _MODEL_NAME / audio_path.stem
        drums_path = output_dir / "drums.wav"
        accompaniment_path = output_dir / "no_drums.wav"

        if not drums_path.exists() or not accompaniment_path.exists():
            raise StemSeparationError("Demucs did not produce the expected output files")

        return SeparatedStems(drums_path=drums_path, accompaniment_path=accompaniment_path)
