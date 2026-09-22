import { generateId } from "./id";
import type { Measure, MusicalPosition, Slot } from "./types";

export const BEATS_PER_MEASURE = 4;
export const SUBDIVISIONS_PER_BEAT = 4;
export const SLOT_DURATION = "16";
const SLOTS_PER_MEASURE = BEATS_PER_MEASURE * SUBDIVISIONS_PER_BEAT;

// Largest-to-smallest so both consolidateRests and consolidateDurations always
// prefer the longest valid value, ordered with their duration in sixteenth-note
// units. Shared between rests and notes: the same "must start on a position
// that's a multiple of its own length" alignment rule applies to both.
const DURATION_SIZES_SIXTEENTHS: { duration: string; sixteenths: number }[] = [
  { duration: "1", sixteenths: 16 },
  { duration: "2", sixteenths: 8 },
  { duration: "4", sixteenths: 4 },
  { duration: "8", sixteenths: 2 },
  { duration: "16", sixteenths: 1 },
];

export function toSixteenthIndex(position: MusicalPosition): number {
  return (position.beat - 1) * SUBDIVISIONS_PER_BEAT + position.subdivision;
}

export function toPosition(measure: number, sixteenthIndex: number): MusicalPosition {
  return {
    measure,
    beat: Math.floor(sixteenthIndex / SUBDIVISIONS_PER_BEAT) + 1,
    subdivision: sixteenthIndex % SUBDIVISIONS_PER_BEAT,
  };
}

// Merges each run of consecutive single-sixteenth rests into the fewest rest
// values that tie together correctly, each aligned so its start position is
// a multiple of its own duration (e.g. a half rest only ever starts on beat
// 1 or 3 of a 4/4 measure) - the engraving convention that keeps rests
// readable instead of an arbitrary run of 16th rests.
export function consolidateRests(slots: Slot[]): Slot[] {
  const result: Slot[] = [];
  let i = 0;

  while (i < slots.length) {
    if (slots[i].type === "note") {
      result.push(slots[i]);
      i++;
      continue;
    }

    let runLength = 0;
    while (i + runLength < slots.length && slots[i + runLength].type === "rest") {
      runLength++;
    }

    const measure = slots[i].position.measure;
    let sixteenthIndex = toSixteenthIndex(slots[i].position);
    let remaining = runLength;
    while (remaining > 0) {
      // The smallest entry (a 16th rest, 1 sixteenth long) always matches
      // here, since sixteenthIndex % 1 is always 0 - .find() can never fall
      // through without a match while remaining > 0.
      const size = DURATION_SIZES_SIXTEENTHS.find(
        ({ sixteenths }) => sixteenths <= remaining && sixteenthIndex % sixteenths === 0,
      )!;
      result.push({
        type: "rest",
        id: generateId("rest"),
        duration: size.duration,
        position: toPosition(measure, sixteenthIndex),
      });
      sixteenthIndex += size.sixteenths;
      remaining -= size.sixteenths;
    }

    i += runLength;
  }

  return result;
}

// Extends each note to absorb as many of its immediately-following rest slots
// as the alignment rule allows (same rule consolidateRests uses for rests: a
// candidate duration may only start on a position that's a multiple of its own
// length), then runs consolidateRests on whatever rests are left over. This is
// how "durations derived from occupied rhythmic positions" (V1-018/#51) works:
// a note's rendered duration is the gap to the next occupied position (or end
// of measure), quantized down to the largest metrically-valid value - not a
// fixed sixteenth.
export function consolidateDurations(slots: Slot[]): Slot[] {
  return consolidateRests(extendNoteDurations(slots));
}

function extendNoteDurations(slots: Slot[]): Slot[] {
  const result: Slot[] = [];
  let i = 0;

  while (i < slots.length) {
    const slot = slots[i];
    if (slot.type !== "note") {
      result.push(slot);
      i++;
      continue;
    }

    let restRun = 0;
    while (i + 1 + restRun < slots.length && slots[i + 1 + restRun].type === "rest") {
      restRun++;
    }

    const sixteenthIndex = toSixteenthIndex(slot.position);
    const capacity = 1 + restRun;
    // The smallest entry (1 sixteenth) always matches, since sixteenthIndex % 1
    // is always 0 and capacity is always >= 1 - .find() can never fall through.
    const size = DURATION_SIZES_SIXTEENTHS.find(
      ({ sixteenths }) => sixteenths <= capacity && sixteenthIndex % sixteenths === 0,
    )!;

    result.push({ ...slot, duration: size.duration });
    i += size.sixteenths;
  }

  return result;
}

// Expands an already-consolidated measure back to one slot per sixteenth, so
// a transformation can edit a single slot before re-consolidating. Every note
// is reset to a single-sixteenth duration at its own index here - any longer
// duration it had (from consolidateDurations) only reflects trailing rests
// that get freshly rebuilt below, so keeping the old duration would
// double-count that span once notes can be longer than one sixteenth.
export function expandMeasure(measure: Measure, measureNumber: number): Slot[] {
  const bySixteenthIndex = new Map<number, Slot>();
  for (const slot of measure) {
    if (slot.type === "note") {
      bySixteenthIndex.set(toSixteenthIndex(slot.position), { ...slot, duration: SLOT_DURATION });
    }
  }

  return Array.from({ length: SLOTS_PER_MEASURE }, (_, index) => {
    const existing = bySixteenthIndex.get(index);
    if (existing) {
      return existing;
    }
    return {
      type: "rest",
      id: generateId("rest"),
      duration: SLOT_DURATION,
      position: toPosition(measureNumber, index),
    };
  });
}
