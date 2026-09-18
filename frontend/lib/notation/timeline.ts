export interface TimelinePoint {
  time: number;
  x: number;
  row: number;
}

const DEFAULT_BEATS_PER_MEASURE = 4;
const DEFAULT_SUBDIVISIONS_PER_BEAT = 4;

export function computeSlotTimeSeconds(
  measure: number,
  beat: number,
  subdivision: number,
  bpm: number,
  beatsPerMeasure: number = DEFAULT_BEATS_PER_MEASURE,
  subdivisionsPerBeat: number = DEFAULT_SUBDIVISIONS_PER_BEAT,
): number {
  const secondsPerBeat = 60 / bpm;
  const totalBeats =
    (measure - 1) * beatsPerMeasure + (beat - 1) + subdivision / subdivisionsPerBeat;
  return totalBeats * secondsPerBeat;
}

export function interpolatePlayheadX(points: TimelinePoint[], time: number): TimelinePoint | null {
  if (points.length === 0) {
    return null;
  }

  if (time <= points[0].time) {
    return points[0];
  }

  const last = points[points.length - 1];
  if (time >= last.time) {
    return last;
  }

  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (time >= a.time && time <= b.time) {
      if (b.time === a.time) {
        return a;
      }
      const ratio = (time - a.time) / (b.time - a.time);
      return { time, x: a.x + (b.x - a.x) * ratio, row: a.row };
    }
  }

  return last;
}
