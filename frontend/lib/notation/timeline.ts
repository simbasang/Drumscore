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
      // Unreachable while points are sorted by non-decreasing time: any
      // pair sharing a.time with an earlier point would already have been
      // matched (and returned) by that earlier bracket first. Guards
      // against a division by zero if that invariant is ever broken.
      if (b.time === a.time) {
        return a;
      }
      const ratio = (time - a.time) / (b.time - a.time);
      return { time, x: a.x + (b.x - a.x) * ratio, row: a.row };
    }
  }

  // Unreachable given sorted points and the clamps above: any time strictly
  // between the first and last point's time is guaranteed to fall inside
  // some consecutive pair. Kept as a safety net if that invariant breaks.
  return last;
}

const DEFAULT_AUTO_SCROLL_MARGIN = 40;

// Keeps a target x position within view, without moving anything while it
// already sits comfortably inside the current viewport - so the playhead
// stays visible during playback without fighting the user's own scrolling.
export function computeAutoScrollLeft(
  currentScrollLeft: number,
  viewportWidth: number,
  targetX: number,
  margin: number = DEFAULT_AUTO_SCROLL_MARGIN,
): number {
  const visibleStart = currentScrollLeft + margin;
  const visibleEnd = currentScrollLeft + viewportWidth - margin;

  if (targetX < visibleStart) {
    return Math.max(0, targetX - margin);
  }
  if (targetX > visibleEnd) {
    return Math.max(0, targetX - viewportWidth + margin);
  }
  return currentScrollLeft;
}
