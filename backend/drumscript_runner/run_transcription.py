import json
import sys
from pathlib import Path

import drumscript as ds


def main() -> None:
    if len(sys.argv) != 4:
        print("Usage: run_transcription.py <audio_path> <output_json_path> <drumscript_output_dir>", file=sys.stderr)
        sys.exit(2)

    audio_path = sys.argv[1]
    events_output_path = Path(sys.argv[2])
    # DrumScript always writes side files (JSON/MIDI/PDF) to output_dir. The
    # caller passes a throwaway directory so they never land next to the audio,
    # which lives in artifact storage where nothing would ever prune them.
    output_dir = Path(sys.argv[3])

    # DrumScript prints progress lines to stdout, so the result is written to a
    # file rather than stdout, which would otherwise mix with that output and
    # break JSON parsing on the caller's side.
    result = ds.transcribe(audio_path, full_song=False, verbose=True, output_dir=str(output_dir))

    events = [
        {"time_sec": event["time_sec"], "instruments": event["instruments"]}
        for event in result["events"]
    ]

    events_output_path.write_text(json.dumps({"events": events}))


if __name__ == "__main__":
    main()
