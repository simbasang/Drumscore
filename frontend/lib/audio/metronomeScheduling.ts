import type { Beat } from "@/lib/api/types";

export function beatPeriodAt(beats: Beat[], sourceTime: number): number | null {
  if (beats.length < 2) {
    return null;
  }

  let index = 0;
  for (let i = 0; i < beats.length; i++) {
    if (beats[i].source_time <= sourceTime) {
      index = i;
    } else {
      break;
    }
  }

  if (index < beats.length - 1) {
    return beats[index + 1].source_time - beats[index].source_time;
  }
  return beats[index].source_time - beats[index - 1].source_time;
}

export function beatsInWindow(beats: Beat[], windowStart: number, windowEnd: number): Beat[] {
  return beats.filter((beat) => beat.source_time >= windowStart && beat.source_time < windowEnd);
}

export function countInClickTimes(beats: Beat[], startTime: number, clickCount: number): number[] {
  const period = beatPeriodAt(beats, startTime);
  if (period == null) {
    return [];
  }
  return Array.from({ length: clickCount }, (_, i) => i * period);
}

// Maps a beat's fixed source-audio timestamp to the real Web Audio context
// deadline it should fire at, given where playback currently is (both in
// source time and real context time) and the current playback rate - one
// second of context time advances sourceTime by `rate` seconds, so covering
// a `(sourceTime - currentSourceTime)` gap takes `/rate` real seconds.
export function contextTimeForSourceTime(
  sourceTime: number,
  currentSourceTime: number,
  currentContextTime: number,
  rate: number,
): number {
  return currentContextTime + (sourceTime - currentSourceTime) / rate;
}
