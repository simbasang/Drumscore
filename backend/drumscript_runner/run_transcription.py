import json
import sys
from pathlib import Path

import drumscript as ds


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: run_transcription.py <audio_path> <output_json_path>", file=sys.stderr)
        sys.exit(2)

    audio_path = sys.argv[1]
    events_output_path = Path(sys.argv[2])

    # The same steps ds.transcribe() runs before building its score. transcribe()
    # itself can't be used: its build_score() snaps every event's time_sec to a
    # 16th grid at DrumScript's own tempo in place, and returns those events, so
    # the source onset times would be lost. Quantization is Drumscore's job.
    audio, sample_rate = ds.load_audio(audio_path, sr=ds.SAMPLE_RATE)
    audio = ds.normalise_audio(audio)
    onsets = ds.detect_onsets(audio, sample_rate)
    classified = ds.classify_events(audio, sample_rate, onsets)

    events = [
        {"time_sec": event["time_sec"], "instruments": event["instruments"]}
        for event in classified
    ]

    # DrumScript prints progress lines to stdout, so the result is written to a
    # file rather than stdout, which would otherwise mix with that output and
    # break JSON parsing on the caller's side.
    events_output_path.write_text(json.dumps({"events": events}))


if __name__ == "__main__":
    main()
